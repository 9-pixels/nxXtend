import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from src.flakes.models import FlakeOutput
from main import _filter_supported_outputs, handle_flakes_upgrade, handle_install, handle_remove


def test_filter_packages():
    outputs = [FlakeOutput(name="vim", type="packages")]
    result = _filter_supported_outputs(outputs)
    assert len(result) == 1 and result[0].type == "packages"


def test_filter_legacy_packages():
    outputs = [FlakeOutput(name="old-pkg", type="legacyPackages")]
    result = _filter_supported_outputs(outputs)
    assert len(result) == 1 and result[0].type == "legacyPackages"


def test_filter_nixos_modules():
    outputs = [FlakeOutput(name="my-mod", type="nixosModules")]
    result = _filter_supported_outputs(outputs)
    assert len(result) == 1 and result[0].type == "nixosModules"


def test_filter_overlays():
    outputs = [FlakeOutput(name="default", type="overlays")]
    result = _filter_supported_outputs(outputs)
    assert len(result) == 1 and result[0].type == "overlays"


def test_filter_excludes_home_manager_modules():
    outputs = [FlakeOutput(name="my-home-mod", type="homeManagerModules")]
    result = _filter_supported_outputs(outputs)
    assert len(result) == 0


def test_filter_excludes_apps():
    outputs = [FlakeOutput(name="myapp", type="apps")]
    result = _filter_supported_outputs(outputs)
    assert len(result) == 0


def test_filter_excludes_devshells():
    outputs = [FlakeOutput(name="default", type="devShells")]
    result = _filter_supported_outputs(outputs)
    assert len(result) == 0


def test_filter_mixed_types():
    outputs = [
        FlakeOutput(name="vim", type="packages"),
        FlakeOutput(name="legacy", type="legacyPackages"),
        FlakeOutput(name="my-mod", type="nixosModules"),
        FlakeOutput(name="default", type="overlays"),
        FlakeOutput(name="myapp", type="apps"),
        FlakeOutput(name="shell", type="devShells"),
        FlakeOutput(name="my-home", type="homeManagerModules"),
    ]
    result = _filter_supported_outputs(outputs)
    types = {o.type for o in result}
    assert types == {"packages", "legacyPackages", "nixosModules", "overlays"}


def test_flakes_upgrade_uses_flake_path_from_config():
    """handle_flakes_upgrade should use flake_path from config"""
    with tempfile.TemporaryDirectory() as tmpdir:
        flake_path = Path(tmpdir) / "flake.nix"
        flake_path.write_text("{}")

        config = {
            "setup": {
                "flake_path": str(flake_path),
            }
        }

        with patch("main.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            handle_flakes_upgrade(config)

            assert mock_run.call_count >= 1
            first_call = mock_run.call_args_list[0]
            assert str(flake_path.parent) in first_call[0][0]


def test_flakes_upgrade_runs_flake_update_then_rebuild():
    """handle_flakes_upgrade should run flake update then nixos-rebuild"""
    with tempfile.TemporaryDirectory() as tmpdir:
        flake_path = Path(tmpdir) / "flake.nix"
        flake_path.write_text("{}")

        config = {
            "setup": {
                "flake_path": str(flake_path),
            }
        }

        with patch("main.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            handle_flakes_upgrade(config)

            assert mock_run.call_count == 2
            update_call = mock_run.call_args_list[0]
            assert "flake" in update_call[0][0]
            assert "update" in update_call[0][0]
            assert str(flake_path.parent) in update_call[0][0]

            rebuild_call = mock_run.call_args_list[1]
            assert "nixos-rebuild" in rebuild_call[0][0]
            assert "switch" in rebuild_call[0][0]
            assert "--flake" in rebuild_call[0][0]
            assert str(flake_path.parent) in rebuild_call[0][0]


def test_flakes_upgrade_stops_on_flake_update_failure():
    """handle_flakes_upgrade should stop if flake update fails"""
    with tempfile.TemporaryDirectory() as tmpdir:
        flake_path = Path(tmpdir) / "flake.nix"
        flake_path.write_text("{}")

        config = {
            "setup": {
                "flake_path": str(flake_path),
            }
        }

        with patch("main.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)  # fail
            handle_flakes_upgrade(config)

            # Should only run flake update, not nixos-rebuild
            assert mock_run.call_count == 1
            assert "update" in mock_run.call_args_list[0][0][0]


# === install/remove rollback regression tests ===


def test_install_rollback_on_rebuild_failure():
    """install should call restore_files when nixos-rebuild fails"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_nix = Path(tmpdir) / "configuration.nix"
        original = '{\n  environment.systemPackages = with pkgs; [\n    git\n  ];\n}'
        config_nix.write_text(original)

        config = {
            "setup": {
                "configuration_path": str(config_nix),
                "flake_enabled": False,
            }
        }

        pkg = MagicMock()
        pkg.name = "vim"
        pkg.source = "stable"
        pkg.version = "9.0"

        def mock_search(name):
            yield "stable", [pkg]
            yield "unstable", []

        with patch("main.search", side_effect=mock_search):
            with patch("main.show_searching"), patch("main.show_done"):
                with patch("main.show_source_select", return_value=1):
                    with patch("main.show_results", return_value=[pkg]):
                        with patch("main.show_summary", return_value=True):
                            with patch("main.subprocess.run") as mock_run:
                                with patch("main.backup_files"):
                                    with patch("main.restore_files") as mock_restore:
                                        mock_run.return_value = MagicMock(returncode=1)
                                        handle_install("vim", config)
                                        mock_restore.assert_called_once()


def test_install_keeps_changes_on_success():
    """install should keep the change when nixos-rebuild succeeds"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_nix = Path(tmpdir) / "configuration.nix"
        original = '{\n  environment.systemPackages = with pkgs; [\n    git\n  ];\n}'
        config_nix.write_text(original)

        config = {
            "setup": {
                "configuration_path": str(config_nix),
                "flake_enabled": False,
            }
        }

        pkg = MagicMock()
        pkg.name = "vim"
        pkg.source = "stable"
        pkg.version = "9.0"

        def mock_search(name):
            yield "stable", [pkg]
            yield "unstable", []

        with patch("main.search", side_effect=mock_search):
            with patch("main.show_searching"), patch("main.show_done"):
                with patch("main.show_source_select", return_value=1):
                    with patch("main.show_results", return_value=[pkg]):
                        with patch("main.show_summary", return_value=True):
                            with patch("main.subprocess.run") as mock_run:
                                with patch("main.backup_files"):
                                    with patch("main.restore_files"):
                                        mock_run.return_value = MagicMock(returncode=0)
                                        handle_install("vim", config)
                                        assert "vim" in config_nix.read_text()




def test_remove_rollback_on_rebuild_failure():
    """remove should call restore_files when nixos-rebuild fails"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_nix = Path(tmpdir) / "configuration.nix"
        original = '{\n  environment.systemPackages = with pkgs; [\n    git\n    vim\n  ];\n}'
        config_nix.write_text(original)

        config = {
            "setup": {
                "configuration_path": str(config_nix),
                "flake_enabled": False,
            }
        }

        with patch("main.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            with patch("main.backup_files"):
                with patch("main.restore_files") as mock_restore:
                    with patch("builtins.input", side_effect=["y"]):
                        handle_remove("vim", config)
                    mock_restore.assert_called_once()


def test_remove_keeps_changes_on_success():
    """remove should keep the deletion when nixos-rebuild succeeds"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_nix = Path(tmpdir) / "configuration.nix"
        original = '{\n  environment.systemPackages = with pkgs; [\n    git\n    vim\n  ];\n}'
        config_nix.write_text(original)

        config = {
            "setup": {
                "configuration_path": str(config_nix),
                "flake_enabled": False,
            }
        }

        with patch("main.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch("main.backup_files"):
                with patch("main.restore_files"):
                    with patch("builtins.input", side_effect=["y", "vim"]):
                        handle_remove("vim", config)
            assert "vim" not in config_nix.read_text()


if __name__ == "__main__":
    tests = [
        test_filter_packages,
        test_filter_legacy_packages,
        test_filter_nixos_modules,
        test_filter_overlays,
        test_filter_excludes_home_manager_modules,
        test_filter_excludes_apps,
        test_filter_excludes_devshells,
        test_filter_mixed_types,
        test_flakes_upgrade_uses_flake_path_from_config,
        test_flakes_upgrade_runs_flake_update_then_rebuild,
        test_flakes_upgrade_stops_on_flake_update_failure,
        test_install_rollback_on_rebuild_failure,
        test_install_keeps_changes_on_success,
        test_remove_rollback_on_rebuild_failure,
        test_remove_keeps_changes_on_success,
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
    print(f"\n  {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
