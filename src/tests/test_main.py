import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from src.flakes.models import FlakeOutput
from main import (
    _filter_supported_outputs, handle_flakes_upgrade, handle_install, handle_remove,
    handle_flakes_install, handle_flakes_remove, _check_flakes_enabled, _check_home_manager_enabled,
)


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
                "flake_enabled": True,
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
                "flake_enabled": True,
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
                "flake_enabled": True,
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


def test_flakes_install_rejected_when_flakes_disabled():
    """nx flakes <url> must be rejected before any file access when flake_enabled=false"""
    config = {"setup": {"flake_enabled": False}}

    with patch("main.parse_flake_url") as mock_parse:
        with patch("main.get_metadata") as mock_meta:
            handle_flakes_install("github:user/repo", config)

    mock_parse.assert_not_called()
    mock_meta.assert_not_called()


def test_flakes_install_rejection_message_mentions_config_path():
    """The rejection message must reference the actual config path from config.py"""
    from src.core.config import CONFIG_FILE
    import io
    from contextlib import redirect_stdout

    config = {"setup": {"flake_enabled": False}}
    buf = io.StringIO()

    # rich Console writes to stdout; capture it
    with patch("main.parse_flake_url"):
        with redirect_stdout(buf):
            handle_flakes_install("github:user/repo", config)

    output = buf.getvalue()
    assert "flake_enabled" in output
    assert str(CONFIG_FILE) in output


def test_flakes_remove_rejected_when_flakes_disabled():
    """nx flakes remove must be rejected before any file access when flake_enabled=false"""
    config = {"setup": {"flake_enabled": False, "flake_path": "/nonexistent/flake.nix"}}

    with patch("main.read_config") as mock_read:
        handle_flakes_remove("some-flake", config)

    mock_read.assert_not_called()


def test_flakes_upgrade_rejected_when_flakes_disabled():
    """nx flakes upgrade must be rejected before running nix when flake_enabled=false"""
    config = {"setup": {"flake_enabled": False, "flake_path": "/nonexistent/flake.nix"}}

    with patch("main.subprocess.run") as mock_run:
        handle_flakes_upgrade(config)

    mock_run.assert_not_called()


def test_flakes_install_works_when_enabled():
    """When flake_enabled=true the workflow must proceed past the guard"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_nix = Path(tmpdir) / "configuration.nix"
        config_nix.write_text('{\n  environment.systemPackages = with pkgs; [\n    git\n  ];\n}')
        config = {
            "setup": {
                "flake_enabled": True,
                "configuration_path": str(config_nix),
            }
        }

        with patch("main.parse_flake_url") as mock_parse:
            with patch("main.get_metadata") as mock_meta:
                with patch("main.get_current_system") as mock_sys:
                    with patch("main.discover", return_value=[]) as mock_disc:
                        mock_sys.return_value = "x86_64-linux"
                        handle_flakes_install("github:user/repo", config)

        mock_parse.assert_called_once()
        mock_disc.assert_called_once()


def test_home_manager_guard_rejects_when_disabled():
    """Operations depending on Home Manager must be rejected when home_manager_enabled=false"""
    config = {"setup": {"home_manager_enabled": False}}
    assert _check_home_manager_enabled(config) is False


def test_home_manager_guard_passes_when_enabled():
    """The same guard must pass when home_manager_enabled=true"""
    config = {"setup": {"home_manager_enabled": True}}
    assert _check_home_manager_enabled(config) is True


def test_flakes_guard_passes_when_enabled():
    """The flakes guard must pass when flake_enabled=true"""
    config = {"setup": {"flake_enabled": True}}
    assert _check_flakes_enabled(config) is True


def test_flakes_guard_rejects_when_disabled():
    """The flakes guard must reject when flake_enabled=false"""
    config = {"setup": {"flake_enabled": False}}
    assert _check_flakes_enabled(config) is False


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
        test_flakes_install_rejected_when_flakes_disabled,
        test_flakes_install_rejection_message_mentions_config_path,
        test_flakes_remove_rejected_when_flakes_disabled,
        test_flakes_upgrade_rejected_when_flakes_disabled,
        test_flakes_install_works_when_enabled,
        test_home_manager_guard_rejects_when_disabled,
        test_home_manager_guard_passes_when_enabled,
        test_flakes_guard_passes_when_enabled,
        test_flakes_guard_rejects_when_disabled,
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
