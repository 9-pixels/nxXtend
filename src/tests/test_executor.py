import sys
import os
import json
import tempfile
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from src.flakes.executor import execute
from src.flakes.models import FlakeSource, FlakeOutput, InstallationPlan


def make_plan(action, pkg_type="packages", name="test-pkg"):
    source = FlakeSource(url="github:user/repo", revision="abc123")
    output = FlakeOutput(name=name, type=pkg_type, attribute=f"{pkg_type}.x86_64-linux.{name}")
    return InstallationPlan(
        source=source,
        output=output,
        action=action,
        system="x86_64-linux",
        flake_name="repo",
    )


def make_config(tmpdir, flake_enabled=False, home_manager_enabled=False):
    return {
        "setup": {
            "configuration_path": str(Path(tmpdir) / "configuration.nix"),
            "flake_enabled": flake_enabled,
            "flake_path": str(Path(tmpdir) / "flake.nix"),
            "home_manager_enabled": home_manager_enabled,
            "home_manager_path": str(Path(tmpdir) / "home.nix"),
        }
    }


def test_unsupported_returns_false_without_rebuild():
    plan = make_plan("unsupported")
    config = {"setup": {"flake_enabled": False}}
    with patch("src.flakes.executor.subprocess.run") as mock_run:
        result = execute(plan, config)
    assert result is False
    mock_run.assert_not_called()


def test_configure_home_returns_false_without_rebuild():
    plan = make_plan("configure_home", pkg_type="homeManagerModules", name="my-mod")
    config = {"setup": {"flake_enabled": False}}
    with patch("src.flakes.executor.subprocess.run") as mock_run:
        result = execute(plan, config)
    assert result is False
    mock_run.assert_not_called()


def test_missing_flake_file_returns_false():
    plan = make_plan("install")
    with tempfile.TemporaryDirectory() as tmpdir:
        config = make_config(tmpdir, flake_enabled=True)
        result = execute(plan, config)
    assert result is False


def test_install_works_with_flakes_disabled():
    plan = make_plan("install", pkg_type="packages", name="vim")
    with tempfile.TemporaryDirectory() as tmpdir:
        config_nix = Path(tmpdir) / "configuration.nix"
        config_nix.write_text('{\n  environment.systemPackages = with pkgs; [\n    git\n  ];\n}')
        config = make_config(tmpdir, flake_enabled=False)
        with patch("src.flakes.executor.subprocess.run") as mock_run:
            with patch("src.flakes.executor.backup_files"):
                mock_run.return_value = MagicMock(returncode=0)
                result = execute(plan, config)
        assert result is True


def test_install_works_with_flakes_enabled():
    plan = make_plan("install", pkg_type="packages", name="vim")
    with tempfile.TemporaryDirectory() as tmpdir:
        flake = Path(tmpdir) / "flake.nix"
        flake.write_text('{\n  inputs = {};\n  outputs = {};\n}')
        config_nix = Path(tmpdir) / "configuration.nix"
        config_nix.write_text('{\n  environment.systemPackages = with pkgs; [\n    git\n  ];\n}')
        config = make_config(tmpdir, flake_enabled=True)
        with patch("src.flakes.executor.subprocess.run") as mock_run:
            with patch("src.flakes.executor.backup_files"):
                with patch("src.flakes.executor.restore_files"):
                    mock_run.return_value = MagicMock(returncode=0)
                    result = execute(plan, config)
        assert result is True


def test_install_works_with_home_manager_enabled():
    plan = make_plan("install", pkg_type="packages", name="vim")
    with tempfile.TemporaryDirectory() as tmpdir:
        flake = Path(tmpdir) / "flake.nix"
        flake.write_text('{\n  inputs = {};\n  outputs = {};\n}')
        home_nix = Path(tmpdir) / "home.nix"
        home_nix.write_text('{\n  home.packages = [];\n}')
        config = make_config(tmpdir, flake_enabled=True, home_manager_enabled=True)
        with patch("src.flakes.executor.subprocess.run") as mock_run:
            with patch("src.flakes.executor.backup_files"):
                with patch("src.flakes.executor.restore_files"):
                    mock_run.return_value = MagicMock(returncode=0)
                    result = execute(plan, config)
        assert result is True


def test_configure_nixos_module():
    plan = make_plan("configure", pkg_type="nixosModules", name="my-mod")
    with tempfile.TemporaryDirectory() as tmpdir:
        flake = Path(tmpdir) / "flake.nix"
        flake.write_text('{\n  inputs = {};\n  outputs = { ... };\n  modules = [];\n}')
        config_nix = Path(tmpdir) / "configuration.nix"
        config_nix.write_text('{\n  environment.systemPackages = with pkgs; [\n    git\n  ];\n}')
        config = make_config(tmpdir, flake_enabled=True)
        with patch("src.flakes.executor.subprocess.run") as mock_run:
            with patch("src.flakes.executor.backup_files"):
                with patch("src.flakes.executor.restore_files"):
                    mock_run.return_value = MagicMock(returncode=0)
                    result = execute(plan, config)
        assert result is True


def test_overlay():
    plan = make_plan("overlay", pkg_type="overlays", name="default")
    with tempfile.TemporaryDirectory() as tmpdir:
        flake = Path(tmpdir) / "flake.nix"
        flake.write_text('{\n  inputs = {};\n  outputs = { ... };\n}')
        config_nix = Path(tmpdir) / "configuration.nix"
        config_nix.write_text('{\n  nixpkgs.overlays = [];\n}')
        config = make_config(tmpdir, flake_enabled=True)
        with patch("src.flakes.executor.subprocess.run") as mock_run:
            with patch("src.flakes.executor.backup_files"):
                with patch("src.flakes.executor.restore_files"):
                    mock_run.return_value = MagicMock(returncode=0)
                    result = execute(plan, config)
        assert result is True


def test_flake_path_from_config():
    plan = make_plan("install", pkg_type="packages", name="vim")
    with tempfile.TemporaryDirectory() as tmpdir:
        subdir = Path(tmpdir) / "my-flake"
        subdir.mkdir()
        flake = subdir / "flake.nix"
        flake.write_text('{\n  inputs = {};\n  outputs = {};\n}')
        config_nix = Path(tmpdir) / "configuration.nix"
        config_nix.write_text('{\n  environment.systemPackages = with pkgs; [\n    git\n  ];\n}')
        config = make_config(tmpdir, flake_enabled=True)
        config["setup"]["flake_path"] = str(flake)
        with patch("src.flakes.executor.subprocess.run") as mock_run:
            with patch("src.flakes.executor.backup_files"):
                with patch("src.flakes.executor.restore_files"):
                    mock_run.return_value = MagicMock(returncode=0)
                    result = execute(plan, config)
        assert result is True


if __name__ == "__main__":
    tests = [
        test_unsupported_returns_false_without_rebuild,
        test_configure_home_returns_false_without_rebuild,
        test_missing_flake_file_returns_false,
        test_install_works_with_flakes_disabled,
        test_install_works_with_flakes_enabled,
        test_install_works_with_home_manager_enabled,
        test_configure_nixos_module,
        test_overlay,
        test_flake_path_from_config,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n  {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
