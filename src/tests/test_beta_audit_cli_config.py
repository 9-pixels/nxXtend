"""Beta audit 2/3 — CLI parsing, config state machine, and rollback safety.

READ-ONLY audit: asserts the intended behaviour of the CLI surface, the
config state machine and rollback safety.

All subprocess/handlers mocked — nothing real runs.
"""
import inspect
import os
from pathlib import Path

import pytest
import toml

from core import config as cfg
from core.target import Target
from core.writer import backup_files, restore_files

import main as m


@pytest.fixture
def sandbox_config(tmp_path):
    """Point the module-level CONFIG_FILE/CONFIG_DIR at a sandbox."""
    orig_file, orig_dir = cfg.CONFIG_FILE, cfg.CONFIG_DIR
    cfg.CONFIG_FILE = tmp_path / "config.toml"
    cfg.CONFIG_DIR = tmp_path
    try:
        yield cfg
    finally:
        cfg.CONFIG_FILE, cfg.CONFIG_DIR = orig_file, orig_dir


# ── [A] CLI adversarial ─────────────────────────────────────────────────────

@pytest.mark.parametrize("argv", [
    ["nx", "install"],
    ["nx", "-i", "-i", "x"],
    ["nx", "-f", "upgrade", "extra"],
    ["nx", "-u", "extra"],
], ids=[
    "A1 install without name → argparse error exit 2",
    "A5 repeated -i → conflicting-ops error (not silent pick)",
    "A8 -f upgrade + extra arg → clean rejection exit 2 (design: no subcommand after -f)",
    "A13 -u with extra arg → clean rejection exit 2 (upgrade takes no positional)",
])
def test_cli_exit_2_with_no_handler(argv, run_cli):
    code, calls, _ = run_cli(argv)
    assert code == 2, f"exit={code}"
    assert not calls


@pytest.mark.parametrize("argv", [
    ["nx", "bogus"],
    ["nx", "-x"],
    ["nx", "setup", "extra"],
], ids=[
    "A3 unknown command → exit 2",
    "A4 unknown flag → exit 2",
    "A16 setup with extra arg → exit 2",
])
def test_cli_exit_2(argv, run_cli):
    code, calls, _ = run_cli(argv)
    assert code == 2, f"exit={code}"


@pytest.mark.parametrize("argv", [
    ["nx", "-f", "remove"],
    ["nx", "flakes", "install"],
    ["nx", "flakes", "remove"],
], ids=[
    "A7 -f remove without name → help/exit, no handler",
    "A9 flakes install without url → help, no handler",
    "A10 flakes remove without name → help, no handler",
])
def test_cli_no_handler_dispatched(argv, run_cli):
    _, calls, _ = run_cli(argv)
    assert not calls


def test_repeated_flake_flag_is_idempotent(run_cli):
    _, calls, _ = run_cli(["nx", "-f", "-f", "github:x/y"])
    assert calls and calls[0][0] == "flakes_install"


def test_non_github_url_is_routed_to_install(run_cli, cli_config):
    # A11: the old URL-prefix gate rejected every non-github reference and
    # fell through to parser.print_help(). The routing fix sends any
    # unrecognised positional to the install path and lets Nix validate it.
    _, calls, _ = run_cli(["nx", "-f", "http://x"])
    assert calls == [("flakes_install", ("http://x", cli_config), {"requested": None})]


def test_home_first_with_install(run_cli, cli_config):
    _, calls, _ = run_cli(["nx", "-H", "-i", "firefox"])
    assert calls == [("install", (["firefox"], cli_config), {"requested": Target.HOME})]


@pytest.mark.parametrize("argv", [
    ["nx", "--home", "-u"],
    ["nx", "-f", "-H", "-u"],
], ids=[
    "A14 --home -u → rejected (unsupported home upgrade)",
    "A15 -f -H -u → rejected before execution",
])
def test_home_upgrade_rejected(argv, run_cli):
    code, calls, _ = run_cli(argv)
    assert code == 1, f"exit={code}"
    assert not calls


# ── [B] Config state machine (sandboxed) ────────────────────────────────────

def test_valid_config_values_preserved(sandbox_config):
    sandbox_config.CONFIG_FILE.write_text('''[setup]
configuration_path = "/custom/configuration.nix"
flake_enabled = true
flake_path = "/custom/flake.nix"
home_manager_enabled = true
home_manager_path = "/custom/home.nix"
unstable_variable = "u9"
[meta]
setup_done = true
''')
    sandbox_config.validate_and_repair()
    data = toml.loads(sandbox_config.CONFIG_FILE.read_text())
    assert data["setup"]["configuration_path"] == "/custom/configuration.nix"
    assert data["setup"]["unstable_variable"] == "u9"
    assert data["meta"]["setup_done"] is True


def test_corrupted_file_repaired_to_defaults(sandbox_config):
    sandbox_config.CONFIG_FILE.write_text("!!!not toml at all [[[")
    sandbox_config.validate_and_repair()
    data = toml.loads(sandbox_config.CONFIG_FILE.read_text())
    assert data["meta"]["setup_done"] is False
    assert data["setup"]["configuration_path"] == "/etc/nixos/configuration.nix"


def test_unrecognised_keys_are_removed_during_repair(sandbox_config):
    """The template is the schema, and everything outside it is dropped.

    Documented behaviour, not a defect: nx owns config.toml, so a key that
    passes no validation and is not part of the template cannot survive a
    repair — otherwise a stale or experimental key could sit in the file and
    be mistaken for a live setting. What matters is that the recognised
    keys and the reserved section headers stay intact.
    """
    sandbox_config.CONFIG_FILE.write_text('''[setup]
configuration_path = "/etc/nixos/configuration.nix"
flake_enabled = true
flake_path = "/etc/nixos/flake.nix"
home_manager_enabled = true
home_manager_path = "/etc/nixos/home.nix"
unstable_variable = "unstable"
[future]
remote_registry = true
custom_note = "keep me"
[my_notes]
todo = "switch to home-manager"
[meta]
setup_done = true
''')
    sandbox_config.validate_and_repair()
    data = toml.loads(sandbox_config.CONFIG_FILE.read_text())

    assert data["setup"]["configuration_path"] == "/etc/nixos/configuration.nix"
    assert data["meta"]["setup_done"] is True
    assert "future" in data and data["future"] == {}, \
        "the reserved section header stays, user keys under it do not"
    assert "my_notes" not in data, "unknown sections are dropped"


def test_invalid_values_repaired_to_defaults(sandbox_config):
    sandbox_config.CONFIG_FILE.write_text('''[setup]
configuration_path = ""
flake_enabled = "yes"
flake_path = 123
home_manager_enabled = "true"
home_manager_path = ""
unstable_variable = "with space"
[meta]
setup_done = "yes"
''')
    sandbox_config.validate_and_repair()
    data = toml.loads(sandbox_config.CONFIG_FILE.read_text())
    s = data["setup"]
    assert s["configuration_path"] == "/etc/nixos/configuration.nix"
    assert s["flake_enabled"] is False
    assert isinstance(s["flake_path"], str)
    assert s["unstable_variable"] == "unstable"
    assert data["meta"]["setup_done"] is False


def test_config_dir_derives_from_sudo_user(monkeypatch):
    """B5: CONFIG_DIR must follow SUDO_USER, falling back to USER.

    The harness version of this check was a tautological label; this version
    actually reloads the module under controlled environment variables and
    restores the original state afterwards.
    """
    import importlib

    orig_sudo = os.environ.get("SUDO_USER")
    orig_user = os.environ.get("USER")
    try:
        monkeypatch.setenv("SUDO_USER", "alice")
        monkeypatch.delenv("USER", raising=False)
        importlib.reload(cfg)
        assert cfg.CONFIG_DIR == Path("/home/alice/.config/nx")

        monkeypatch.delenv("SUDO_USER")
        monkeypatch.setenv("USER", "bob")
        importlib.reload(cfg)
        assert cfg.CONFIG_DIR == Path("/home/bob/.config/nx")
    finally:
        if orig_sudo is None:
            os.environ.pop("SUDO_USER", None)
        else:
            os.environ["SUDO_USER"] = orig_sudo
        if orig_user is None:
            os.environ.pop("USER", None)
        else:
            os.environ["USER"] = orig_user
        importlib.reload(cfg)


# ── [C] Rollback safety ─────────────────────────────────────────────────────

def test_backup_restore_roundtrip(tmp_path):
    f1 = tmp_path / "a.nix"
    f1.write_text("A-content")
    f2 = tmp_path / "b.nix"
    f2.write_text("B-content")
    backup_files([f1, f2], backup_dir=tmp_path / "bk")
    f1.write_text("A-mangled")
    f2.write_text("B-mangled")
    restore_files([f1, f2], backup_dir=tmp_path / "bk")
    assert f1.read_text() == "A-content"
    assert f2.read_text() == "B-content"


def test_second_backup_overwrites_first(tmp_path):
    f1 = tmp_path / "a.nix"
    f1.write_text("A-content")
    backup_files([f1], backup_dir=tmp_path / "bk")
    f1.write_text("A-mangled")
    # second transaction overwrites the backup with MANGLED content
    backup_files([f1], backup_dir=tmp_path / "bk")
    f1.write_text("A-worse")
    restore_files([f1], backup_dir=tmp_path / "bk")
    # Documented design: the single backup slot holds the MANGLED intermediate,
    # so the prior good state is lost.
    assert f1.read_text() == "A-mangled"


def test_default_backup_dir_is_hardcoded():
    from core import writer as w
    src = inspect.getsource(w.backup_files)
    assert "/etc/nixos/.nx-backup" in src


def test_same_basename_files_collide_in_flat_backup(tmp_path):
    d1, d2 = tmp_path / "sys", tmp_path / "home"
    d1.mkdir()
    d2.mkdir()
    f1 = d1 / "configuration.nix"
    f1.write_text("SYS")
    f2 = d2 / "configuration.nix"
    f2.write_text("HOME-DIR")
    backup_files([f1, f2], backup_dir=tmp_path / "bk")
    assert (tmp_path / "bk" / "configuration.nix").read_text() == "HOME-DIR"


# ── [D] handle_upgrade rebuild-dir derivation (informational) ───────────────

def test_upgrade_derives_flake_dir_from_configuration_path():
    src = inspect.getsource(m.handle_upgrade)
    assert "configuration_path" in src
    assert "flake_path" not in src
