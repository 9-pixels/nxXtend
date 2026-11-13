"""Target selection tests (SYSTEM/HOME).

Migrated from the original script harness; every ``check`` maps 1:1 to a
collected pytest test instance. Checks that were tautological labels in the
harness (``check(..., True)``) are now real assertions against the mocked
collaborators they were annotating.
"""
import argparse
import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.target import (
    Target, select_target, resolve_target_info, require_home_manager,
    SYSTEM_BLOCK, HOME_BLOCK,
)
from main import handle_install, handle_flakes_install


def make_config(tmpdir, home_enabled=False, flake_enabled=False):
    return {
        "setup": {
            "configuration_path": str(Path(tmpdir) / "configuration.nix"),
            "flake_enabled": flake_enabled,
            "flake_path": str(Path(tmpdir) / "flake.nix"),
            "home_manager_enabled": home_enabled,
            "home_manager_path": str(Path(tmpdir) / "home.nix"),
            "unstable_variable": "unstable",
        }
    }


def parse(argv):
    """Rebuild main's parser exactly and parse argv."""
    parser = argparse.ArgumentParser(prog="nx")
    parser.add_argument("--version", "-v", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("setup")

    def add_home_flag(subparser):
        subparser.add_argument(
            "-H", "--home", "-home",
            action="store_const", const=Target.HOME, dest="home_target",
        )

    install_p = subparsers.add_parser("install")
    install_p.add_argument("name")
    add_home_flag(install_p)
    remove_p = subparsers.add_parser("remove")
    remove_p.add_argument("name")
    add_home_flag(remove_p)
    upgrade_p = subparsers.add_parser("upgrade")
    add_home_flag(upgrade_p)
    flakes_p = subparsers.add_parser("flakes")
    flakes_p.add_argument("action_or_url", nargs="?")
    flakes_p.add_argument("name", nargs="?")
    add_home_flag(flakes_p)
    return parser.parse_args(argv)


# ── [1] select_target: pure decision ────────────────────────────────────────

@pytest.mark.parametrize("config,requested,expected", [
    ({"setup": {}}, None, Target.SYSTEM),
    ({"setup": {"home_manager_enabled": True}}, None, Target.SYSTEM),
    ({"setup": {}}, Target.HOME, Target.HOME),
    ({"setup": {}}, Target.SYSTEM, Target.SYSTEM),
], ids=[
    "no request → SYSTEM",
    "no request → SYSTEM even with HM enabled",
    "HOME request → HOME",
    "SYSTEM request → SYSTEM",
])
def test_select_target_pure_decision(config, requested, expected):
    assert select_target(config, requested) is expected


# ── [2] require_home_manager: availability gate ─────────────────────────────

@pytest.mark.parametrize("config,expected", [
    ({"setup": {"home_manager_enabled": False}}, False),
    ({"setup": {}}, False),
    ({"setup": {"home_manager_enabled": True}}, True),
], ids=[
    "false when disabled",
    "false when missing",
    "true when enabled",
])
def test_require_home_manager(config, expected):
    assert require_home_manager(config) is expected


# ── [3] resolve_target_info: file + block mapping ───────────────────────────

def test_resolve_target_info_file_and_block(tmp_path):
    config = make_config(tmp_path, home_enabled=True)
    info = resolve_target_info(config, Target.SYSTEM)
    assert info.file == tmp_path / "configuration.nix"
    assert info.block == SYSTEM_BLOCK
    info = resolve_target_info(config, Target.HOME)
    assert info.file == tmp_path / "home.nix"
    assert info.block == HOME_BLOCK


# ── [4] CLI flag normalization (argparse against main's parser) ─────────────

@pytest.mark.parametrize("sub,extra", [
    ("install", ["firefox"]),
    ("remove", ["firefox"]),
    ("upgrade", []),
    ("flakes", ["github:x/y"]),
], ids=["install", "remove", "upgrade", "flakes"])
@pytest.mark.parametrize("flag", ["-H", "--home", "-home"])
def test_home_flag_selects_home(sub, extra, flag):
    args = parse([sub, flag] + extra)
    assert args.home_target is Target.HOME


@pytest.mark.parametrize("sub,extra", [
    ("install", ["firefox"]),
    ("remove", ["firefox"]),
    ("upgrade", []),
    ("flakes", ["github:x/y"]),
], ids=["install", "remove", "upgrade", "flakes"])
def test_no_flag_leaves_home_target_none(sub, extra):
    args = parse([sub] + extra)
    assert args.home_target is None


def test_home_flag_after_positional():
    args = parse(["install", "firefox", "-H"])
    assert args.home_target is Target.HOME


# ── [5] -H with home_manager_enabled=false → clean reject ──────────────────

def test_home_request_rejected_when_hm_disabled(tmp_path):
    config = make_config(tmp_path, home_enabled=False)
    with patch("main.search") as mock_search:
        with patch("main.backup_files") as mock_backup:
            buf = io.StringIO()
            with redirect_stdout(buf):
                handle_install("firefox", config, requested=Target.HOME)
    mock_search.assert_not_called()
    mock_backup.assert_not_called()
    out = buf.getvalue()
    assert "home_manager_enabled" in out
    assert ".config/nx/config.toml" in out


# ── [6] THE critical test: -H must NOT enter Flake workflow ─────────────────

def test_home_request_does_not_enter_flake_workflow(tmp_path):
    config = make_config(tmp_path, home_enabled=True, flake_enabled=False)

    conf = tmp_path / "configuration.nix"
    home = tmp_path / "home.nix"
    conf.write_text('{ pkgs, ... }:\n{\n  environment.systemPackages = with pkgs; [ git ];\n}\n')
    home.write_text('{ pkgs, ... }:\n{\n  home.packages = with pkgs; [ git ];\n}\n')

    pkg = MagicMock()
    pkg.name = "firefox"
    pkg.attribute = "firefox"
    pkg.source = "stable"
    pkg.version = "1.0"

    def mock_search(name):
        yield "stable", [pkg]
        yield "unstable", []

    with patch("main.search", side_effect=mock_search):
        with patch("main.show_searching"), patch("main.show_done"):
            with patch("main.show_source_select", return_value=1):
                with patch("main.show_results", return_value=[pkg]):
                    with patch("main.show_summary", return_value=True):
                        with patch("main.subprocess.run") as mock_run:
                            mock_run.return_value = MagicMock(returncode=0)
                            with patch("main.backup_files"):
                                with patch("main.restore_files"):
                                    with patch("main.add_flake") as mock_add_flake:
                                        handle_install("firefox", config,
                                                       requested=Target.HOME)
                                        mock_add_flake.assert_not_called()

    assert mock_run.called
    assert "home.packages" in home.read_text()


# ── [7] nx flakes -H: parses target, preserves flake guard ──────────────────

def test_flakes_guard_rejects_when_flakes_disabled(tmp_path):
    config = make_config(tmp_path, home_enabled=True, flake_enabled=False)
    with patch("main.parse_flake_url") as mock_parse:
        handle_flakes_install("github:x/y", config, requested=Target.HOME)
    mock_parse.assert_not_called()


def test_flakes_home_rejected_when_hm_disabled(tmp_path):
    config = make_config(tmp_path, home_enabled=False, flake_enabled=True)
    with patch("main.parse_flake_url") as mock_parse:
        handle_flakes_install("github:x/y", config, requested=Target.HOME)
    mock_parse.assert_not_called()


def test_flakes_home_proceeds_to_resolver_when_both_enabled(tmp_path):
    config = make_config(tmp_path, home_enabled=True, flake_enabled=True)
    (tmp_path / "home.nix").write_text(
        '{ pkgs, ... }:\n{\n  home.packages = with pkgs; [\n    git\n  ];\n}\n')
    with patch("main.parse_flake_url") as mock_parse:
        with patch("main.get_metadata"):
            with patch("main.get_current_system", return_value="x86_64-linux"):
                with patch("main.discover", return_value=[]):
                    handle_flakes_install("github:x/y", config, requested=Target.HOME)
    mock_parse.assert_called_once()


# ── [8] executor conflation regression ──────────────────────────────────────

def test_executor_flake_enabled_alone_decides_flake_workflow(tmp_path):
    from flakes.executor import execute
    from flakes.models import FlakeSource, FlakeOutput, InstallationPlan

    plan = InstallationPlan(
        source=FlakeSource(url="github:x/y"),
        output=FlakeOutput(name="default", type="packages"),
        action="install", system="x86_64-linux", flake_name="y",
    )

    config = make_config(tmp_path, home_enabled=True, flake_enabled=False)
    conf = tmp_path / "configuration.nix"
    conf.write_text('{ pkgs, ... }:\n{\n  environment.systemPackages = with pkgs; [ git ];\n}\n')
    with patch("flakes.executor.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("flakes.executor.backup_files"):
            with patch("flakes.executor.add_flake") as mock_add_flake:
                execute(plan, config)
                mock_add_flake.assert_not_called()
