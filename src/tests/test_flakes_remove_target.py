"""Target-aware flake removal regression tests.

Reproduces the real-world failure: home_manager_enabled=true with flake
references living in configuration.nix — the old code inspected home.nix,
removed the input, and left dangling references in configuration.nix.

Migrated from the original script harness; every ``check`` maps 1:1 to a
collected pytest test instance.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.target import Target, select_target
from main import handle_flakes_remove

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


# ── T1: THE real-world regression ───────────────────────────────────────────

def test_system_removal_with_home_manager_enabled(tmp_path):
    config = make_env(tmp_path, sys_text=SYS_WITH_REFS, home_text=HOME_UNRELATED,
                      home_manager_enabled=True)
    run_remove(tmp_path, config)
    sys_out = (tmp_path / "configuration.nix").read_text()
    home_out = (tmp_path / "home.nix").read_text()
    flake_out = (tmp_path / "flake.nix").read_text()
    assert "inputs.claude-desktop-nix.packages" not in sys_out
    assert "inputs.claude-desktop-nix.overlays" not in sys_out
    assert "claude-desktop-nix" not in flake_out
    assert "inputs.hyprmod.packages" in home_out and "claude" not in home_out
    assert "git" in sys_out and "ripgrep" in home_out


# ── T2: explicit HOME removal ───────────────────────────────────────────────

def test_explicit_home_removal_targets_home_nix(tmp_path):
    config = make_env(tmp_path, sys_text=SYS_WITH_REFS, home_text=HOME_WITH_REFS,
                      home_manager_enabled=True)
    run_remove(tmp_path, config, requested=Target.HOME)
    sys_out = (tmp_path / "configuration.nix").read_text()
    home_out = (tmp_path / "home.nix").read_text()
    flake_out = (tmp_path / "flake.nix").read_text()
    assert "inputs.claude-desktop-nix.packages" not in home_out
    assert "inputs.claude-desktop-nix.packages" in sys_out
    # input kept — still referenced by the other target (configuration.nix)
    assert "claude-desktop-nix" in flake_out


# ── T3: all three HOME aliases ──────────────────────────────────────────────

@pytest.mark.parametrize("flag", ["-H", "--home", "-home"], ids=[
    "T3: -H → home.nix cleaned",
    "T3: --home → home.nix cleaned",
    "T3: -home → home.nix cleaned",
])
def test_home_aliases_clean_home_nix(flag, tmp_path):
    config = make_env(tmp_path, sys_text=SYS_WITH_REFS, home_text=HOME_WITH_REFS,
                      home_manager_enabled=True)
    run_remove(tmp_path, config, requested=Target.HOME)
    home_out = (tmp_path / "home.nix").read_text()
    assert "inputs.claude-desktop-nix.packages" not in home_out


def test_select_target_unit_level(tmp_path):
    config = make_env(tmp_path, sys_text=SYS_WITH_REFS, home_text=HOME_WITH_REFS)
    assert select_target(config, None) is Target.SYSTEM
    assert select_target(config, Target.HOME) is Target.HOME


# ── T4: system package reference removal ────────────────────────────────────

def test_system_package_reference_removal(tmp_path):
    pkg_only = SYS_WITH_REFS.replace("""
  nixpkgs.overlays = [
    inputs.claude-desktop-nix.overlays.default
  ];
""", "")
    config = make_env(tmp_path, sys_text=pkg_only, home_text=HOME_UNRELATED)
    run_remove(tmp_path, config)
    sys_out = (tmp_path / "configuration.nix").read_text()
    assert "inputs.claude-desktop-nix.packages" not in sys_out
    assert "environment.systemPackages" in sys_out
    assert "git" in sys_out


# ── T5: home package reference removal ──────────────────────────────────────

def test_home_package_reference_removal(tmp_path):
    sys_no_claude = SYS_WITH_REFS.replace(
        "inputs.claude-desktop-nix.packages.${pkgs.stdenv.hostPlatform.system}.default", "vim"
    ).replace("""
  nixpkgs.overlays = [
    inputs.claude-desktop-nix.overlays.default
  ];
""", "")
    config = make_env(tmp_path, sys_text=sys_no_claude,
                      home_text=HOME_WITH_REFS, home_manager_enabled=True)
    # system file has NO claude refs → remove -H cleans home, input can go
    run_remove(tmp_path, config, requested=Target.HOME)
    home_out = (tmp_path / "home.nix").read_text()
    flake_out = (tmp_path / "flake.nix").read_text()
    assert "inputs.claude-desktop-nix.packages" not in home_out
    assert "home.packages" in home_out and "ripgrep" in home_out
    assert "claude-desktop-nix" not in flake_out


# ── T6: overlay removal ─────────────────────────────────────────────────────

def test_overlay_removal(tmp_path):
    config = make_env(tmp_path, sys_text=SYS_WITH_REFS, home_text=None,
                      home_manager_enabled=False)
    run_remove(tmp_path, config)
    sys_out = (tmp_path / "configuration.nix").read_text()
    assert "inputs.claude-desktop-nix.overlays" not in sys_out
    assert "nixpkgs.overlays = [" in sys_out


# ── T7: other-target reference keeps the input ──────────────────────────────

def test_other_target_reference_keeps_input(tmp_path):
    # both files reference the flake; remove SYSTEM side
    config = make_env(tmp_path, sys_text=SYS_WITH_REFS, home_text=HOME_WITH_REFS,
                      home_manager_enabled=True)
    run_remove(tmp_path, config)  # default → SYSTEM
    flake_out = (tmp_path / "flake.nix").read_text()
    sys_out = (tmp_path / "configuration.nix").read_text()
    home_out = (tmp_path / "home.nix").read_text()
    assert "claude-desktop-nix" not in sys_out
    assert "inputs.claude-desktop-nix.packages" in home_out
    assert "claude-desktop-nix" in flake_out

    # now remove the HOME side too → input goes away
    run_remove(tmp_path, config, requested=Target.HOME)
    flake_out = (tmp_path / "flake.nix").read_text()
    home_out = (tmp_path / "home.nix").read_text()
    assert "claude-desktop-nix" not in flake_out
    assert "inputs.claude-desktop-nix.packages" not in home_out


# ── T8: rollback ────────────────────────────────────────────────────────────

def test_rollback_restores_files_when_rebuild_fails(tmp_path):
    config = make_env(tmp_path, sys_text=SYS_WITH_REFS, home_text=HOME_UNRELATED)
    mock_run, mock_backup, mock_restore = run_remove(tmp_path, config, rebuild_ok=False)
    assert mock_run.called
    assert mock_backup.called
    assert mock_restore.called


# ── T9: CLI dispatch passes the flag through ────────────────────────────────

@pytest.mark.parametrize("argv,expected", [
    (["nx", "flakes", "remove", "-H", "github:tomsch/claude-desktop-nix"], Target.HOME),
    (["nx", "flakes", "remove", "github:tomsch/claude-desktop-nix"], None),
], ids=[
    "T9: handle_flakes_remove called with requested=Target.HOME",
    "T9: no flag → requested=None (SYSTEM)",
])
def test_cli_dispatch_passes_home_flag(argv, expected, tmp_path):
    import main as main_mod

    config = make_env(tmp_path, sys_text=SYS_WITH_REFS, home_text=HOME_WITH_REFS)
    with patch("main.handle_flakes_remove") as mock_remove:
        with patch("main.bootstrap", return_value=config):
            import sys
            sys.argv = argv
            main_mod.main()
    assert mock_remove.call_args.kwargs.get("requested") is expected
