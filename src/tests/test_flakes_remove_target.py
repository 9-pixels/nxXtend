"""Target-aware flake removal regression tests (Phase 2).

Reproduces the real-world failure: home_manager_enabled=true with flake
references living in configuration.nix — the old code inspected home.nix,
removed the input, and left dangling references in configuration.nix.
"""
import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from src.core.target import Target, select_target, resolve_target_info
from main import handle_flakes_remove

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f" — {detail}" if not cond else ""))


# Realistic fixtures modeled on the live /etc/nixos files.

FLAKE_NIX = '''{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    claude-desktop-nix = {
      url = "github:tomsch/claude-desktop-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    }; # nx
  };
  outputs = { nixpkgs, claude-desktop-nix, ... }@inputs: {
  };
}
'''

SYS_WITH_REFS = '''{ config, pkgs, inputs, unstable, ... }:
{
  environment.systemPackages = with pkgs; [
    git
    inputs.claude-desktop-nix.packages.${pkgs.stdenv.hostPlatform.system}.default
  ];

  nixpkgs.overlays = [
    inputs.claude-desktop-nix.overlays.default
  ];
}
'''

HOME_WITH_REFS = '''{ config, pkgs, inputs, ... }:
{
  home.packages = with pkgs; [
    ripgrep
    inputs.claude-desktop-nix.packages.${pkgs.stdenv.hostPlatform.system}.default
  ];
}
'''

HOME_UNRELATED = '''{ config, pkgs, inputs, ... }:
{
  home.packages = with pkgs; [
    ripgrep
    inputs.hyprmod.packages.${pkgs.stdenv.hostPlatform.system}.default
  ];
}
'''


def make_env(tmpdir, sys_text=None, home_text=None, home_manager_enabled=True):
    """Build a temp /etc/nixos-like environment. Returns config dict."""
    flake = Path(tmpdir) / "flake.nix"
    flake.write_text(FLAKE_NIX)
    if sys_text is not None:
        (Path(tmpdir) / "configuration.nix").write_text(sys_text)
    if home_text is not None:
        (Path(tmpdir) / "home.nix").write_text(home_text)
    return {
        "setup": {
            "configuration_path": str(Path(tmpdir) / "configuration.nix"),
            "flake_enabled": True,
            "flake_path": str(flake),
            "home_manager_enabled": home_manager_enabled,
            "home_manager_path": str(Path(tmpdir) / "home.nix"),
        }
    }


def run_remove(tmpdir, config, name="claude-desktop-nix", requested=None,
               rebuild_ok=True):
    with patch("main.subprocess.run") as mock_run:
        with patch("main.backup_files") as mock_backup:
            with patch("main.restore_files") as mock_restore:
                mock_run.return_value = MagicMock(returncode=0 if rebuild_ok else 1)
                handle_flakes_remove(name, config, requested=requested)
    return mock_run, mock_backup, mock_restore


print("=" * 70)
print("TARGET-AWARE FLAKE REMOVAL — REGRESSION TESTS")
print("=" * 70)

# ── Test 1: THE real-world regression ─────────────────────────────────────
print("\n[T1] System removal with Home Manager enabled (the original bug)")

with tempfile.TemporaryDirectory() as tmpdir:
    config = make_env(tmpdir, sys_text=SYS_WITH_REFS, home_text=HOME_UNRELATED,
                      home_manager_enabled=True)
    run_remove(tmpdir, config)
    sys_out = (Path(tmpdir) / "configuration.nix").read_text()
    home_out = (Path(tmpdir) / "home.nix").read_text()
    flake_out = (Path(tmpdir) / "flake.nix").read_text()
    check("T1: package reference removed from configuration.nix",
          "inputs.claude-desktop-nix.packages" not in sys_out)
    check("T1: overlay reference removed from configuration.nix",
          "inputs.claude-desktop-nix.overlays" not in sys_out)
    check("T1: input removed from flake.nix",
          "claude-desktop-nix" not in flake_out)
    check("T1: home.nix untouched (unrelated refs intact)",
          "inputs.hyprmod.packages" in home_out and "claude" not in home_out)
    check("T1: other packages preserved",
          "git" in sys_out and "ripgrep" in home_out)

# ── Test 2: explicit HOME removal ─────────────────────────────────────────
print("\n[T2] Explicit -H removal targets home.nix")

with tempfile.TemporaryDirectory() as tmpdir:
    config = make_env(tmpdir, sys_text=SYS_WITH_REFS, home_text=HOME_WITH_REFS,
                      home_manager_enabled=True)
    run_remove(tmpdir, config, requested=Target.HOME)
    sys_out = (Path(tmpdir) / "configuration.nix").read_text()
    home_out = (Path(tmpdir) / "home.nix").read_text()
    flake_out = (Path(tmpdir) / "flake.nix").read_text()
    check("T2: reference removed from home.nix",
          "inputs.claude-desktop-nix.packages" not in home_out)
    check("T2: configuration.nix untouched",
          "inputs.claude-desktop-nix.packages" in sys_out)
    # input kept — still referenced by the other target (configuration.nix)
    check("T2: input KEPT in flake.nix (other target still references it)",
          "claude-desktop-nix" in flake_out)

# ── Test 3: all three HOME aliases ────────────────────────────────────────
print("\n[T3] -H / --home / -home all select Target.HOME")

for flag in ("-H", "--home", "-home"):
    with tempfile.TemporaryDirectory() as tmpdir:
        config = make_env(tmpdir, sys_text=SYS_WITH_REFS, home_text=HOME_WITH_REFS,
                          home_manager_enabled=True)
        run_remove(tmpdir, config, requested=Target.HOME)
        home_out = (Path(tmpdir) / "home.nix").read_text()
        check(f"T3: {flag} → home.nix cleaned",
              "inputs.claude-desktop-nix.packages" not in home_out)

# select_target unit-level (no I/O)
check("T3: select_target(None) → SYSTEM", select_target(config, None) is Target.SYSTEM)
check("T3: select_target(Target.HOME) → HOME", select_target(config, Target.HOME) is Target.HOME)

# ── Test 4: system package reference removal ──────────────────────────────
print("\n[T4] System package reference removal")

with tempfile.TemporaryDirectory() as tmpdir:
    pkg_only = SYS_WITH_REFS.replace("""
  nixpkgs.overlays = [
    inputs.claude-desktop-nix.overlays.default
  ];
""", "")
    config = make_env(tmpdir, sys_text=pkg_only, home_text=HOME_UNRELATED)
    run_remove(tmpdir, config)
    sys_out = (Path(tmpdir) / "configuration.nix").read_text()
    check("T4: package ref removed, block intact",
          "inputs.claude-desktop-nix.packages" not in sys_out
          and "environment.systemPackages" in sys_out and "git" in sys_out)

# ── Test 5: home package reference removal ────────────────────────────────
print("\n[T5] Home package reference removal")

with tempfile.TemporaryDirectory() as tmpdir:
    sys_no_claude = SYS_WITH_REFS.replace(
        "inputs.claude-desktop-nix.packages.${pkgs.stdenv.hostPlatform.system}.default", "vim"
    ).replace("""
  nixpkgs.overlays = [
    inputs.claude-desktop-nix.overlays.default
  ];
""", "")
    config = make_env(tmpdir, sys_text=sys_no_claude,
                      home_text=HOME_WITH_REFS, home_manager_enabled=True)
    # system file has NO claude refs → remove -H cleans home, input can go
    run_remove(tmpdir, config, requested=Target.HOME)
    home_out = (Path(tmpdir) / "home.nix").read_text()
    flake_out = (Path(tmpdir) / "flake.nix").read_text()
    check("T5: home ref removed, block intact",
          "inputs.claude-desktop-nix.packages" not in home_out
          and "home.packages" in home_out and "ripgrep" in home_out)
    check("T5: input removed (no other references)",
          "claude-desktop-nix" not in flake_out)

# ── Test 6: overlay removal ───────────────────────────────────────────────
print("\n[T6] Overlay removal (no regression)")

with tempfile.TemporaryDirectory() as tmpdir:
    config = make_env(tmpdir, sys_text=SYS_WITH_REFS, home_text=None,
                      home_manager_enabled=False)
    run_remove(tmpdir, config)
    sys_out = (Path(tmpdir) / "configuration.nix").read_text()
    check("T6: overlay reference removed",
          "inputs.claude-desktop-nix.overlays" not in sys_out)
    check("T6: overlays block structure preserved",
          "nixpkgs.overlays = [" in sys_out)

# ── Test 7: other-target reference keeps the input ────────────────────────
print("\n[T7] Remaining reference on the other target keeps the input")

with tempfile.TemporaryDirectory() as tmpdir:
    # both files reference the flake; remove SYSTEM side
    config = make_env(tmpdir, sys_text=SYS_WITH_REFS, home_text=HOME_WITH_REFS,
                      home_manager_enabled=True)
    run_remove(tmpdir, config)  # default → SYSTEM
    flake_out = (Path(tmpdir) / "flake.nix").read_text()
    sys_out = (Path(tmpdir) / "configuration.nix").read_text()
    home_out = (Path(tmpdir) / "home.nix").read_text()
    check("T7: system refs removed", "claude-desktop-nix" not in sys_out)
    check("T7: home refs intact (not scanned for mutation)",
          "inputs.claude-desktop-nix.packages" in home_out)
    check("T7: input KEPT (home still references it)",
          "claude-desktop-nix" in flake_out)

    # now remove the HOME side too → input goes away
    run_remove(tmpdir, config, requested=Target.HOME)
    flake_out = (Path(tmpdir) / "flake.nix").read_text()
    home_out = (Path(tmpdir) / "home.nix").read_text()
    check("T7: after both removes, input fully removed",
          "claude-desktop-nix" not in flake_out)
    check("T7: home refs cleaned on second remove",
          "inputs.claude-desktop-nix.packages" not in home_out)

# ── Test 8: rollback ──────────────────────────────────────────────────────
print("\n[T8] Rollback restores files when rebuild fails")

with tempfile.TemporaryDirectory() as tmpdir:
    config = make_env(tmpdir, sys_text=SYS_WITH_REFS, home_text=HOME_UNRELATED)
    mock_run, mock_backup, mock_restore = run_remove(tmpdir, config, rebuild_ok=False)
    check("T8: rebuild attempted", mock_run.called)
    check("T8: backup taken before write", mock_backup.called)
    check("T8: restore called on failure", mock_restore.called)

# ── Dispatch: -H reaches handle_flakes_remove ─────────────────────────────
print("\n[T9] CLI dispatch passes the flag through")

import main as main_mod
from unittest.mock import patch as _patch

with tempfile.TemporaryDirectory() as tmpdir:
    config = make_env(tmpdir, sys_text=SYS_WITH_REFS, home_text=HOME_WITH_REFS)
    with _patch("main.handle_flakes_remove") as mock_remove:
        with _patch("main.bootstrap", return_value=config):
            sys.argv = ["nx", "flakes", "remove", "-H", "github:tomsch/claude-desktop-nix"]
            main_mod.main()
    check("T9: handle_flakes_remove called with requested=Target.HOME",
          mock_remove.call_args.kwargs.get("requested") is Target.HOME)

with tempfile.TemporaryDirectory() as tmpdir:
    config = make_env(tmpdir, sys_text=SYS_WITH_REFS, home_text=HOME_WITH_REFS)
    with _patch("main.handle_flakes_remove") as mock_remove:
        with _patch("main.bootstrap", return_value=config):
            sys.argv = ["nx", "flakes", "remove", "github:tomsch/claude-desktop-nix"]
            main_mod.main()
    check("T9: no flag → requested=None (SYSTEM)",
          mock_remove.call_args.kwargs.get("requested") is None)


print("\n" + "=" * 70)
print(f"RESULTS: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    for f in FAIL:
        print(f"  ✗ {f}")
print("=" * 70)
sys.exit(1 if FAIL else 0)
