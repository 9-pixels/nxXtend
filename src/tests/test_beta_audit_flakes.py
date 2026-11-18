"""Beta audit 3/3 — flake discovery, install/remove integration, E2E sandbox.

READ-ONLY audit: asserts CORRECT behavior; the checks that fail are known
defects and are pinned with ``pytest.mark.xfail(strict=True, ...)`` so a
defect that gets fixed surfaces as an XPASS and fails the suite.

All nix subprocesses mocked; files live in tmp_path.
"""
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.target import Target
from core.writer import add_flake, remove_flake, remove_flake_reference
from flakes.discovery import discover, classify
from flakes.executor import execute
from flakes.models import FlakeOutput, FlakeSource, InstallationPlan
from flakes.resolver import parse_flake_url

import main as main_mod


FLAKE = '{\n  inputs = {\n    nixpkgs.url = "github:NixOS/nixpkgs";\n  };\n  outputs = { nixpkgs, ... }: {\n  };\n}\n'
HOME = '{ pkgs, ... }:\n{\n  home.packages = with pkgs; [\n    git\n  ];\n}\n'
SYS = '{ pkgs, ... }:\n{\n  environment.systemPackages = with pkgs; [\n    git\n  ];\n}\n'


def fake_discover(json_payload, system="x86_64-linux"):
    """Run discover() with mocked nix commands."""
    with patch("flakes.discovery.subprocess.run") as mock_run:
        def side_effect(cmd, **kw):
            m = MagicMock()
            if "show" in cmd:
                m.returncode = 0
                m.stdout = json.dumps(json_payload)
            else:  # eval currentSystem
                m.returncode = 0
                m.stdout = system
            return m
        mock_run.side_effect = side_effect
        return discover(FlakeSource(url="github:x/y"))


# ── [A] Discovery adversarial ───────────────────────────────────────────────

@pytest.mark.parametrize("payload,length,first", [
    ({"packages": {"x86_64-linux": {"default": {}, "vim": {}, "htop": {}}}},
     3, {"name": "default"}),
    ({"packages": {"aarch64-darwin": {"vim": {}}}}, 0, None),
    ({"packages": {"x86_64-linux": "not-a-dict"}}, 0, None),
    ({"packages": "not-a-dict"}, 0, None),
    ({"hydraJobs": {"x86_64-linux": {"x": {}}}}, 0, None),
    ({}, 0, None),
    ({"packages": {"x86_64-linux": {}}, "overlays": {"default": {}}},
     1, {"type": "overlays"}),
], ids=[
    "A1 default ordered first",
    "A2 wrong-system outputs excluded",
    "A3 non-dict system content skipped",
    "A4 non-dict type content skipped",
    "A5 unknown output type (hydraJobs) ignored",
    "A6 empty outputs → empty list",
    "A7 empty system dict + overlay present → overlay only",
])
def test_discovery_adversarial(payload, length, first):
    out = fake_discover(payload)
    assert len(out) == length
    if first is not None:
        for key, value in first.items():
            assert getattr(out[0], key) == value


def test_malformed_json_is_handled(capsys):
    """A8 (fixed): `flake show` exiting 0 with a non-JSON body is reported,
    never raised.

    The raw body is the only evidence of what the command produced, so it is
    shown verbatim alongside the parse error.
    """
    with patch("flakes.discovery.subprocess.run") as mr:
        m = MagicMock()
        m.returncode = 0
        m.stdout = "{invalid json"
        mr.return_value = m
        out = discover(FlakeSource(url="github:x/y"))
    assert out == []
    captured = capsys.readouterr().out
    assert "invalid JSON" in captured, captured
    assert "{invalid json" in captured, "the raw body must be shown"


def test_nix_failure_returns_empty_list():
    with patch("flakes.discovery.subprocess.run") as mr:
        m = MagicMock()
        m.returncode = 1
        m.stdout = ""
        mr.return_value = m
        out = discover(FlakeSource(url="github:x/y"))
    assert out == []


# ── [B] classify coverage ───────────────────────────────────────────────────

@pytest.mark.parametrize("output_type,expected", [
    ("packages", "installable"),
    ("legacyPackages", "installable"),
    ("nixosModules", "configurable"),
    ("homeManagerModules", "configurable"),
    ("apps", "executable"),
    ("overlays", "overlay"),
    ("devShells", "unsupported"),
    ("checks", "unsupported"),
    ("bogusType", "unsupported"),
], ids=[
    "B packages → installable",
    "B legacyPackages → installable",
    "B nixosModules → configurable",
    "B homeManagerModules → configurable",
    "B apps → executable",
    "B overlays → overlay",
    "B devShells → unsupported",
    "B checks → unsupported",
    "B bogusType → unsupported",
])
def test_classify_coverage(output_type, expected):
    got = classify(FlakeOutput(name="x", type=output_type))
    assert got == expected, f"got {got}"


# ── [C] resolver ────────────────────────────────────────────────────────────

def test_resolver_url_with_target_split():
    s = parse_flake_url("github:user/repo#packages.x86_64-linux.vim")
    assert s.url == "github:user/repo"
    assert s.target == "packages.x86_64-linux.vim"


def test_resolver_plain_url():
    s = parse_flake_url("github:user/repo")
    assert s.url == "github:user/repo"
    assert s.target is None


# ── [D] add_flake / remove round trips (writer level) ──────────────────────

def test_add_flake_home_round_trip():
    fc, hc, st = add_flake(FLAKE, "test-flake", "github:x/y", "default", "package",
                           home_content=HOME, block="home.packages")
    assert 'url = "github:x/y"' in fc
    assert "inputs.test-flake.packages" in hc
    assert st == "success"


def test_repeated_install_does_not_duplicate_input():
    """D2 (fixed): a repeat install must report success.

    The input is not duplicated (unchanged), and the status must be
    "success" — callers treat anything else as a reason to restore the
    backups and skip the rebuild, which made an idempotent re-run look like
    a failed rebuild.
    """
    fc, hc, st = add_flake(FLAKE, "test-flake", "github:x/y", "default", "package",
                           home_content=HOME, block="home.packages")
    fc2, hc2, st2 = add_flake(fc, "test-flake", "github:x/y", "default", "package",
                              home_content=hc, block="home.packages")
    input_count = fc2.count('url = "github:x/y"')
    assert input_count == 1, f"input occurrences: {input_count}"
    assert st2 == "success"


def test_remove_flake_removes_input():
    fc, hc, st = add_flake(FLAKE, "test-flake", "github:x/y", "default", "package",
                           home_content=HOME, block="home.packages")
    fc2, hc2, st2 = add_flake(fc, "test-flake", "github:x/y", "default", "package",
                              home_content=hc, block="home.packages")
    fc3, found = remove_flake(fc2, "test-flake")
    assert found
    assert "test-flake" not in fc3


def test_remove_flake_reference_with_spaces_inside_interpolation():
    weird = '  inputs.x.packages.${ pkgs.system }.default\n'
    out, found = remove_flake_reference(weird, "x")
    assert found, f"found={found!r} out={out!r}"


def test_remove_flake_reference_non_default_overlay_attr():
    ov = '    inputs.x.overlays.my-overlay\n'
    out, found = remove_flake_reference(ov, "x")
    assert found


# ── [E] executor integration (sandboxed) ────────────────────────────────────

def make_plan(action="install", pkg_type="packages", name="default"):
    return InstallationPlan(
        source=FlakeSource(url="github:x/y", revision="abc"),
        output=FlakeOutput(name=name, type=pkg_type,
                           attribute=f"{pkg_type}.x86_64-linux.{name}"),
        action=action, system="x86_64-linux", flake_name="repo")


def make_config(td, flake_enabled=True, hm=True):
    return {"setup": {
        "configuration_path": str(Path(td) / "configuration.nix"),
        "flake_enabled": flake_enabled,
        "flake_path": str(Path(td) / "flake.nix"),
        "home_manager_enabled": hm,
        "home_manager_path": str(Path(td) / "home.nix"),
        "unstable_variable": "unstable",
    }}


def setup_env(td, sys_text=None, home_text=None, flake_text=FLAKE):
    if flake_text is not None:
        Path(td, "flake.nix").write_text(flake_text)
    if sys_text is not None:
        Path(td, "configuration.nix").write_text(sys_text)
    if home_text is not None:
        Path(td, "home.nix").write_text(home_text)


def run_exec(td, plan, config, target=None):
    with patch("flakes.executor.subprocess.run") as mr, \
         patch("flakes.executor.backup_files"), \
         patch("flakes.executor.restore_files"):
        mr.return_value = MagicMock(returncode=0)
        ok = execute(plan, config, target=target)
        rebuild_cmd = mr.call_args[0][0] if mr.called else None
    return ok, rebuild_cmd


def test_executor_rebuild_uses_flake_flag(tmp_path):
    setup_env(tmp_path, sys_text=SYS, home_text=HOME)
    ok, cmd = run_exec(tmp_path, make_plan(), make_config(tmp_path))
    assert ok and cmd and cmd[0] == "nixos-rebuild" and "--flake" in cmd, \
        f"ok={ok} cmd={cmd}"


def test_non_flake_path_rebuild_command(tmp_path):
    """E2 (fixed): a non-flake install must write the package into the target
    file and then rebuild.

    The block has to come from the same decision as the target file. The old
    code called add_package() without a block, so detect_format() looked for
    environment.systemPackages inside home.nix, reported an unsupported
    format, restored the backups and issued no rebuild at all.
    """
    setup_env(tmp_path, sys_text=SYS, home_text=HOME)
    ok, cmd = run_exec(tmp_path, make_plan(), make_config(tmp_path, flake_enabled=False))
    assert ok, f"ok={ok} cmd={cmd}"
    assert cmd and cmd[0] == "nixos-rebuild" and "--flake" in cmd, f"cmd={cmd}"
    assert Path(tmp_path, "home.nix").read_text() != HOME, \
        "the package was not written into home.nix"
    assert Path(tmp_path, "configuration.nix").read_text() == SYS, \
        "the package leaked into configuration.nix"


def test_non_flake_path_explicit_system_target(tmp_path):
    """The same path with an explicit system target writes configuration.nix."""
    setup_env(tmp_path, sys_text=SYS, home_text=HOME)
    ok, cmd = run_exec(tmp_path, make_plan(), make_config(tmp_path, flake_enabled=False),
                       target=Target.SYSTEM)
    assert ok and cmd, f"ok={ok} cmd={cmd}"
    assert Path(tmp_path, "configuration.nix").read_text() != SYS
    assert Path(tmp_path, "home.nix").read_text() == HOME


def test_non_flake_repeated_install_is_not_a_failure(tmp_path):
    """The non-flake counterpart of D2.

    A package already in the list yields "no_change" from add_package(). That
    is the requested state, not a failure: the old check restored the backups
    and skipped the rebuild, so a harmless re-run was reported as a broken
    rebuild.
    """
    setup_env(tmp_path, sys_text=SYS, home_text=HOME)
    plan = make_plan()
    ok, cmd = run_exec(tmp_path, plan, make_config(tmp_path, flake_enabled=False))
    assert ok and cmd, f"first install: ok={ok} cmd={cmd}"
    ok2, cmd2 = run_exec(tmp_path, plan, make_config(tmp_path, flake_enabled=False))
    assert ok2, f"repeat install reported a failure: ok={ok2}"
    assert cmd2, "a repeat install must still rebuild"


def test_executor_missing_flake_nix(tmp_path):
    setup_env(tmp_path, sys_text=SYS, home_text=HOME, flake_text=None)
    if Path(tmp_path, "flake.nix").exists():
        Path(tmp_path, "flake.nix").unlink()
    ok, cmd = run_exec(tmp_path, make_plan(), make_config(tmp_path))
    assert ok is False and cmd is None, f"ok={ok} cmd={cmd}"


def test_executor_home_target_without_home_nix(tmp_path):
    setup_env(tmp_path, sys_text=SYS, home_text=None)
    ok, cmd = run_exec(tmp_path, make_plan(), make_config(tmp_path), target=Target.HOME)
    assert ok is False and cmd is None, f"ok={ok} cmd={cmd}"


def test_executor_overlay_with_home_target(tmp_path):
    setup_env(tmp_path, sys_text=SYS, home_text=HOME)
    run_exec(tmp_path, make_plan(action="overlay", pkg_type="overlays"),
             make_config(tmp_path), target=Target.HOME)
    home_after = Path(tmp_path, "home.nix").read_text()
    # Semantics are undefined; this records the current behaviour.
    assert "nixpkgs.overlays" in home_after


# ── [F] E2E sandbox: full install→remove cycle via handlers ────────────────

def run_handler_install(url, config, requested=None):
    outs = [FlakeOutput(name="default", type="packages",
                        attribute="packages.x86_64-linux.default")]
    with patch("main.parse_flake_url", return_value=FlakeSource(url=url)), \
         patch("main.get_metadata", return_value=FlakeSource(url=url)), \
         patch("main.discover", return_value=outs), \
         patch("main.get_current_system", return_value="x86_64-linux"), \
         patch("main.show_results_flake", return_value=[outs[0]]), \
         patch("main.show_summary", return_value=True), \
         patch("main.show_rebuild_start"), patch("main.show_rebuild_done"), \
         patch("main.subprocess.run") as mr, \
         patch("main.backup_files"), patch("main.restore_files"), \
         patch("flakes.executor.backup_files"), \
         patch("flakes.executor.restore_files"), \
         redirect_stdout(io.StringIO()):
        mr.return_value = MagicMock(returncode=0)
        main_mod.handle_flakes_install(url, config, requested=requested)


def test_e2e_install_system(tmp_path):
    setup_env(tmp_path, sys_text=SYS, home_text=HOME)
    cfg = make_config(tmp_path)
    run_handler_install("github:test/repo", cfg)  # SYSTEM default
    sys_txt = Path(tmp_path, "configuration.nix").read_text()
    home_txt = Path(tmp_path, "home.nix").read_text()
    assert "inputs.repo.packages" in sys_txt
    assert home_txt == HOME


def test_e2e_install_home(tmp_path):
    setup_env(tmp_path, sys_text=SYS, home_text=HOME)
    cfg = make_config(tmp_path)
    run_handler_install("github:test/repo", cfg, requested=Target.HOME)
    home_txt = Path(tmp_path, "home.nix").read_text()
    sys_txt = Path(tmp_path, "configuration.nix").read_text()
    assert "inputs.repo.packages" in home_txt
    assert sys_txt == SYS


def test_e2e_unmanaged_reference_refused(tmp_path):
    setup_env(tmp_path, sys_text=SYS, home_text=HOME)
    Path(tmp_path, "configuration.nix").write_text(SYS.replace(
        "git", "git\n    inputs.evil-flake.someCustom.thing"))
    cfg = make_config(tmp_path)
    with patch("main.subprocess.run") as mr, \
         patch("main.backup_files"), patch("main.restore_files"), \
         redirect_stdout(io.StringIO()) as buf:
        mr.return_value = MagicMock(returncode=0)
        main_mod.handle_flakes_remove("evil-flake", cfg)
    assert not mr.called
    assert "unmanaged" in buf.getvalue()


def test_e2e_repeated_remove(tmp_path):
    setup_env(tmp_path, sys_text=SYS, home_text=HOME)
    cfg = make_config(tmp_path)
    run_handler_install("github:test/repo", cfg)
    with patch("main.subprocess.run") as mr, patch("main.backup_files"), \
         patch("main.restore_files"), redirect_stdout(io.StringIO()):
        mr.return_value = MagicMock(returncode=0)
        main_mod.handle_flakes_remove("repo", cfg)
        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            main_mod.handle_flakes_remove("repo", cfg)
    assert "not found" in buf2.getvalue()
