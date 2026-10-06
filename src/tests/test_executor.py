import sys
import os
import json
import tempfile
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from flakes.executor import execute
from flakes.models import FlakeSource, FlakeOutput, InstallationPlan
from core.target import Target


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
    with patch("flakes.executor.subprocess.run") as mock_run:
        result = execute(plan, config)
    assert result is False
    mock_run.assert_not_called()


def test_configure_home_returns_false_without_rebuild():
    plan = make_plan("configure_home", pkg_type="homeManagerModules", name="my-mod")
    config = {"setup": {"flake_enabled": False}}
    with patch("flakes.executor.subprocess.run") as mock_run:
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
        with patch("flakes.executor.subprocess.run") as mock_run:
            with patch("flakes.executor.backup_files"):
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
        with patch("flakes.executor.subprocess.run") as mock_run:
            with patch("flakes.executor.backup_files"):
                with patch("flakes.executor.restore_files"):
                    mock_run.return_value = MagicMock(returncode=0)
                    result = execute(plan, config)
        assert result is True


def test_flake_install_unsupported_format_rolls_back_no_rebuild():
    """Flake install must NOT rebuild when the target block is unsupported."""
    plan = make_plan("install", pkg_type="packages", name="vim")
    with tempfile.TemporaryDirectory() as tmpdir:
        flake = Path(tmpdir) / "flake.nix"
        flake.write_text('{ \n  inputs = {};\n  outputs = {};\n}')
        config_nix = Path(tmpdir) / "configuration.nix"
        # empty block — unsupported
        config_nix.write_text('{ \n  environment.systemPackages = [ ]; \n}')
        config = make_config(tmpdir, flake_enabled=True)
        with patch("flakes.executor.subprocess.run") as mock_run:
            with patch("flakes.executor.backup_files"):
                with patch("flakes.executor.restore_files") as mock_restore:
                    mock_run.return_value = MagicMock(returncode=0)
                    result = execute(plan, config)
        assert result is False, "must not succeed on unsupported format"
        mock_restore.assert_called_once(), "backups must be restored"
        mock_run.assert_not_called(), "rebuild must not happen"


def test_install_works_with_home_manager_enabled():
    plan = make_plan("install", pkg_type="packages", name="vim")
    with tempfile.TemporaryDirectory() as tmpdir:
        flake = Path(tmpdir) / "flake.nix"
        flake.write_text('{\n  inputs = {};\n  outputs = {};\n}')
        home_nix = Path(tmpdir) / "home.nix"
        # Supported format — the test's purpose is HM routing, not format handling
        home_nix.write_text('{\n  home.packages = with pkgs; [\n    git\n  ];\n}')
        config = make_config(tmpdir, flake_enabled=True, home_manager_enabled=True)
        with patch("flakes.executor.subprocess.run") as mock_run:
            with patch("flakes.executor.backup_files"):
                with patch("flakes.executor.restore_files"):
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
        with patch("flakes.executor.subprocess.run") as mock_run:
            with patch("flakes.executor.backup_files"):
                with patch("flakes.executor.restore_files"):
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
        with patch("flakes.executor.subprocess.run") as mock_run:
            with patch("flakes.executor.backup_files"):
                with patch("flakes.executor.restore_files"):
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
        with patch("flakes.executor.subprocess.run") as mock_run:
            with patch("flakes.executor.backup_files"):
                with patch("flakes.executor.restore_files"):
                    mock_run.return_value = MagicMock(returncode=0)
                    result = execute(plan, config)
        assert result is True


# ── Flake target routing (Step 4) ──────────────────────────────────────────

FLAKE_STUB = '{\n  inputs = {};\n  outputs = {};\n}'
SYS_STUB = '{\n  environment.systemPackages = with pkgs; [\n    git\n  ];\n}'
HOME_STUB = '{\n  home.packages = with pkgs; [\n    git\n  ];\n}'


def _run_install(tmpdir, target=None, home_manager_enabled=False,
                 sys_text=SYS_STUB, home_text=HOME_STUB, create_home=True,
                 create_sys=True):
    flake = Path(tmpdir) / "flake.nix"
    flake.write_text(FLAKE_STUB)
    if create_sys:
        (Path(tmpdir) / "configuration.nix").write_text(sys_text)
    if create_home:
        (Path(tmpdir) / "home.nix").write_text(home_text)
    config = make_config(tmpdir, flake_enabled=True,
                         home_manager_enabled=home_manager_enabled)
    plan = make_plan("install", pkg_type="packages", name="vim")
    with patch("flakes.executor.subprocess.run") as mock_run:
        with patch("flakes.executor.backup_files"):
            with patch("flakes.executor.restore_files"):
                mock_run.return_value = MagicMock(returncode=0)
                result = execute(plan, config, target=target)
    sys_out = (Path(tmpdir) / "configuration.nix").read_text() if (Path(tmpdir) / "configuration.nix").exists() else ""
    home_out = (Path(tmpdir) / "home.nix").read_text() if (Path(tmpdir) / "home.nix").exists() else ""
    return result, flake.read_text(), sys_out, home_out


def test_home_target_routes_reference_to_home_nix():
    """nx flakes -H <repo>: input → flake.nix, reference → home.packages"""
    with tempfile.TemporaryDirectory() as tmpdir:
        result, flake_out, sys_out, home_out = _run_install(tmpdir, target=Target.HOME)
        assert result is True
        assert 'url = "github:user/repo"' in flake_out, "flake input must be in flake.nix"
        assert "inputs.repo.packages" in home_out, "reference must be in home.nix"
        assert "inputs.repo.packages" not in sys_out, "SYSTEM file must be untouched"
        assert "inputs.repo.packages" not in flake_out, "reference must not be in flake.nix"


def test_home_target_reference_is_inside_home_packages():
    """The reference must be inside the home.packages list, not appended elsewhere."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result, flake_out, sys_out, home_out = _run_install(tmpdir, target=Target.HOME)
        assert result is True
        # reference line sits between home.packages = [ and its closing ]
        import re
        m = re.search(r'home\.packages\s*=\s*(?:with pkgs;\s*)?\[(.*?)\]', home_out, re.DOTALL)
        assert m, "home.packages block must exist"
        assert "inputs.repo.packages" in m.group(1), "reference must be INSIDE home.packages"


def test_system_target_routes_reference_to_configuration_nix():
    """nx flakes <repo> (explicit SYSTEM): input → flake.nix, reference → systemPackages"""
    with tempfile.TemporaryDirectory() as tmpdir:
        result, flake_out, sys_out, home_out = _run_install(tmpdir, target=Target.SYSTEM)
        assert result is True
        assert 'url = "github:user/repo"' in flake_out
        assert "inputs.repo.packages" in sys_out, "reference must be in configuration.nix"
        assert "inputs.repo.packages" not in home_out, "HOME file must be untouched"


def test_system_target_overrides_home_manager_inference():
    """THE regression: no -H + home_manager_enabled=true must still target
    configuration.nix when target=SYSTEM is explicit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result, flake_out, sys_out, home_out = _run_install(
            tmpdir, target=Target.SYSTEM, home_manager_enabled=True)
        assert result is True
        assert "inputs.repo.packages" in sys_out, "SYSTEM target must win over HM inference"
        assert "inputs.repo.packages" not in home_out


def test_legacy_none_target_keeps_hm_inference():
    """target=None (legacy callers): home_manager_enabled still routes to home.nix."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result, flake_out, sys_out, home_out = _run_install(
            tmpdir, target=None, home_manager_enabled=True)
        assert result is True
        assert "inputs.repo.packages" in home_out
        assert "inputs.repo.packages" not in sys_out


def test_home_target_plain_list_syntax():
    """home.packages = [ (no with pkgs) must also receive the reference."""
    plain = '{\n  home.packages = [\n    pkgs.git\n  ];\n}'
    with tempfile.TemporaryDirectory() as tmpdir:
        result, flake_out, sys_out, home_out = _run_install(
            tmpdir, target=Target.HOME, home_text=plain)
        assert result is True
        assert "inputs.repo.packages" in home_out


def test_home_target_missing_home_nix_fails_cleanly():
    """HOME target with no home.nix → False, and configuration.nix must NOT
    receive the reference."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result, flake_out, sys_out, home_out = _run_install(
            tmpdir, target=Target.HOME, create_home=False)
        assert result is False
        assert "inputs.repo.packages" not in sys_out, "must not write to wrong file"
        assert "inputs.repo" not in flake_out or "url" not in flake_out


def test_system_target_missing_configuration_nix_fails_cleanly():
    """SYSTEM target with no configuration.nix → False, home.nix untouched."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result, flake_out, sys_out, home_out = _run_install(
            tmpdir, target=Target.SYSTEM, create_sys=False)
        assert result is False
        assert "inputs.repo.packages" not in home_out, "must not write to wrong file"


def test_home_target_missing_home_packages_block():
    """HOME target, home.nix exists but lacks home.packages → Beta contract:
    unsupported_missing, execute returns False, nothing written, no rebuild."""
    no_block = '{\n  home.username = "ayman";\n}\n'
    with tempfile.TemporaryDirectory() as tmpdir:
        result, flake_out, sys_out, home_out = _run_install(
            tmpdir, target=Target.HOME, home_text=no_block)
        assert result is False
        assert home_out == no_block, "home.nix must remain byte-for-byte unchanged"
        assert "home.packages" not in home_out, "nx must not create the block"
        assert "inputs.repo.packages" not in home_out
        # the reference must NOT have leaked into flake.nix as a package entry
        import re
        leak = re.search(r'packages\.\$\{[^}]+\}\.vim', flake_out)
        assert not leak, "reference must not leak into flake.nix"


def test_backward_compat_system_flake_unchanged():
    """Legacy default (no target, HM off) behaves exactly as before Step 4."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result, flake_out, sys_out, home_out = _run_install(
            tmpdir, target=None, home_manager_enabled=False)
        assert result is True
        assert "inputs.repo.packages" in sys_out
        assert "inputs.repo.packages" not in home_out


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
        test_home_target_routes_reference_to_home_nix,
        test_home_target_reference_is_inside_home_packages,
        test_system_target_routes_reference_to_configuration_nix,
        test_system_target_overrides_home_manager_inference,
        test_legacy_none_target_keeps_hm_inference,
        test_home_target_plain_list_syntax,
        test_home_target_missing_home_nix_fails_cleanly,
        test_system_target_missing_configuration_nix_fails_cleanly,
        test_home_target_missing_home_packages_block,
        test_backward_compat_system_flake_unchanged,
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
