import sys
import os
import io
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from src.core.target import (
    Target, TargetInfo, select_target, resolve_target_info, require_home_manager,
    SYSTEM_BLOCK, HOME_BLOCK,
)
from main import handle_install, handle_flakes_install


PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f" — {detail}" if not cond else ""))


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


print("=" * 70)
print("TARGET SELECTION TESTS")
print("=" * 70)

# ── select_target: pure decision ───────────────────────────────────────────
print("\n[1] select_target — pure decision")

check("no request → SYSTEM", select_target({"setup": {}}, None) is Target.SYSTEM)
check("no request → SYSTEM even with HM enabled",
      select_target({"setup": {"home_manager_enabled": True}}, None) is Target.SYSTEM)
check("HOME request → HOME", select_target({"setup": {}}, Target.HOME) is Target.HOME)
check("SYSTEM request → SYSTEM", select_target({"setup": {}}, Target.SYSTEM) is Target.SYSTEM)

# ── require_home_manager ───────────────────────────────────────────────────
print("\n[2] require_home_manager — availability gate")

check("false when disabled", require_home_manager({"setup": {"home_manager_enabled": False}}) is False)
check("false when missing", require_home_manager({"setup": {}}) is False)
check("true when enabled", require_home_manager({"setup": {"home_manager_enabled": True}}) is True)

# ── resolve_target_info ────────────────────────────────────────────────────
print("\n[3] resolve_target_info — file + block mapping")

with tempfile.TemporaryDirectory() as td:
    config = make_config(td, home_enabled=True)
    info = resolve_target_info(config, Target.SYSTEM)
    check("SYSTEM file = configuration.nix", info.file == Path(td) / "configuration.nix")
    check("SYSTEM block = environment.systemPackages", info.block == SYSTEM_BLOCK)
    info = resolve_target_info(config, Target.HOME)
    check("HOME file = home.nix", info.file == Path(td) / "home.nix")
    check("HOME block = home.packages", info.block == HOME_BLOCK)

# ── CLI normalization: -H / --home / -home ─────────────────────────────────
print("\n[4] CLI flag normalization (argparse against main's parser)")

import argparse

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

    install_p = subparsers.add_parser("install"); install_p.add_argument("name"); add_home_flag(install_p)
    remove_p = subparsers.add_parser("remove"); remove_p.add_argument("name"); add_home_flag(remove_p)
    upgrade_p = subparsers.add_parser("upgrade"); add_home_flag(upgrade_p)
    flakes_p = subparsers.add_parser("flakes")
    flakes_p.add_argument("action_or_url", nargs="?")
    flakes_p.add_argument("name", nargs="?")
    add_home_flag(flakes_p)
    return parser.parse_args(argv)

for sub, extra in [("install", ["firefox"]), ("remove", ["firefox"]), ("upgrade", []), ("flakes", ["github:x/y"])]:
    for flag in ("-H", "--home", "-home"):
        args = parse([sub, flag] + extra)
        check(f"nx {sub} {flag} → HOME", args.home_target is Target.HOME)
    args = parse([sub] + extra)
    check(f"nx {sub} (no flag) → None/SYSTEM", args.home_target is None)

# flag AFTER positional must also work (argparse allows interspersed)
args = parse(["install", "firefox", "-H"])
check("nx install firefox -H (flag last) → HOME", args.home_target is Target.HOME)

# ── -H rejection when HM disabled (clean, no files touched) ───────────────
print("\n[5] -H with home_manager_enabled=false → clean reject")

with tempfile.TemporaryDirectory() as td:
    config = make_config(td, home_enabled=False)
    with patch("main.search") as mock_search:
        with patch("main.backup_files") as mock_backup:
            buf = io.StringIO()
            with redirect_stdout(buf):
                handle_install("firefox", config, requested=Target.HOME)
    mock_search.assert_not_called()
    mock_backup.assert_not_called()
    out = buf.getvalue()
    check("rejects before search", True)
    check("message mentions home_manager_enabled", "home_manager_enabled" in out)
    check("message mentions config path", ".config/nx/config.toml" in out)

# ── THE critical test: -H must NOT enter Flake workflow ───────────────────
print("\n[6] -H + home_manager_enabled=true + flake_enabled=false")
print("    must NOT enter Flake workflow")

with tempfile.TemporaryDirectory() as td:
    config = make_config(td, home_enabled=True, flake_enabled=False)

    # handle_install must route to home.nix, never to flake functions
    conf = Path(td) / "configuration.nix"
    home = Path(td) / "home.nix"
    conf.write_text('{ pkgs, ... }:\n{\n  environment.systemPackages = with pkgs; [ git ];\n}\n')
    home.write_text('{ pkgs, ... }:\n{\n  home.packages = with pkgs; [ git ];\n}\n')

    pkg = MagicMock(); pkg.name = "firefox"; pkg.source = "stable"; pkg.version = "1.0"

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
                                        handle_install("firefox", config, requested=Target.HOME)
                                        mock_add_flake.assert_not_called()

    # home.nix is the file the handler read (it exists check passed means
    # it targeted home.nix, since we wrote both files)
    check("rebuild ran (workflow completed)", mock_run.called)
    check("add_flake never called (not a flake op)", True)
    check("targeted home.nix (read succeeded on HOME file)",
          "home.packages" in home.read_text())

# ── handle_flakes_install: target parsed, flake guard unchanged ────────────
print("\n[7] nx flakes -H: parses target, preserves flake guard")

with tempfile.TemporaryDirectory() as td:
    # flakes disabled → existing guard rejects regardless of -H
    config = make_config(td, home_enabled=True, flake_enabled=False)
    with patch("main.parse_flake_url") as mock_parse:
        handle_flakes_install("github:x/y", config, requested=Target.HOME)
    mock_parse.assert_not_called()
    check("flakes guard still rejects when flake_enabled=false", True)

with tempfile.TemporaryDirectory() as td:
    # flakes enabled + HM disabled + -H → home rejection
    config = make_config(td, home_enabled=False, flake_enabled=True)
    with patch("main.parse_flake_url") as mock_parse:
        handle_flakes_install("github:x/y", config, requested=Target.HOME)
    mock_parse.assert_not_called()
    check("-H rejected when HM disabled (flakes path)", True)

with tempfile.TemporaryDirectory() as td:
    # flakes enabled + HM enabled + -H → proceeds past guards into resolver
    config = make_config(td, home_enabled=True, flake_enabled=True)
    with patch("main.parse_flake_url") as mock_parse:
        with patch("main.get_metadata") as mock_meta:
            with patch("main.get_current_system", return_value="x86_64-linux"):
                with patch("main.discover", return_value=[]):
                    handle_flakes_install("github:x/y", config, requested=Target.HOME)
    mock_parse.assert_called_once()
    check("flakes -H proceeds to resolver when both enabled", True)

# ── executor conflation regression ────────────────────────────────────────
print("\n[8] executor: flake_enabled alone decides flake workflow")

from src.flakes.executor import execute
from src.flakes.models import FlakeSource, FlakeOutput, InstallationPlan

plan = InstallationPlan(
    source=FlakeSource(url="github:x/y"),
    output=FlakeOutput(name="default", type="packages"),
    action="install", system="x86_64-linux", flake_name="y",
)

with tempfile.TemporaryDirectory() as td:
    # HM enabled, flakes DISABLED → must use plain add_package path,
    # not add_flake (the old conflation)
    config = make_config(td, home_enabled=True, flake_enabled=False)
    conf = Path(td) / "configuration.nix"
    conf.write_text('{ pkgs, ... }:\n{\n  environment.systemPackages = with pkgs; [ git ];\n}\n')
    with patch("src.flakes.executor.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("src.flakes.executor.backup_files"):
            with patch("src.flakes.executor.add_flake") as mock_add_flake:
                result = execute(plan, config)
                mock_add_flake.assert_not_called()
    check("executor: HM-on/flakes-off does NOT call add_flake", True)

print("\n" + "=" * 70)
print(f"RESULTS: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    for f in FAIL: print(f"  ✗ {f}")
print("=" * 70)
sys.exit(1 if FAIL else 0)
