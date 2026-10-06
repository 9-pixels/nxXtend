import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, '/home/ayman/Projects/nix-install')

from core.config import (
    CONFIG_TEMPLATE, SETUP_DEFAULTS, validate_setup_value, validate_and_repair,
    create_fresh_config, load_config, is_setup_done, mark_setup_complete,
    CONFIG_DIR, CONFIG_FILE
)


# ─── Test fixtures ─────────────────────────────────────────────────────────────

VALID_WITH_PKGS = """# nx configuration
# This file contains user-configurable settings for nx.
# Changes to this file may affect how nx reads and writes your NixOS setup.


# ─────────────────────────────────────────────
# NixOS setup
# ─────────────────────────────────────────────


[setup]

configuration_path = "/custom/path/configuration.nix"

flake_enabled = true
flake_path = "/etc/nixos/flake.nix"

home_manager_enabled = false
home_manager_path = "/etc/nixos/home.nix"

unstable_variable = "myPkgs"

# ─────────────────────────────────────────────
# Future features
# ─────────────────────────────────────────────

[future]

# Features planned for future nx versions.
# These options are currently informational only.

# Remote Flake metadata registry.
# remote_registry = false

# Package file shortcuts.
[shortcuts]
# Nothing yet

# ─────────────────────────────────────────────
# Internal state
# ─────────────────────────────────────────────

[meta]

# Internal state managed by nx.
# Do not edit these values manually.

setup_done = true
"""

MISSING_UNSTABLE_VAR = """# nx configuration
# This file contains user-configurable settings for nx.
# Changes to this file may affect how nx reads and writes your NixOS setup.


# ─────────────────────────────────────────────
# NixOS setup
# ─────────────────────────────────────────────


[setup]

configuration_path = "/custom/path/configuration.nix"

flake_enabled = true
flake_path = "/etc/nixos/flake.nix"

home_manager_enabled = false
home_manager_path = "/etc/nixos/home.nix"

# ─────────────────────────────────────────────
# Future features
# ─────────────────────────────────────────────

[future]

# Features planned for future nx versions.
# These options are currently informational only.

# Remote Flake metadata registry.
# remote_registry = false

# Package file shortcuts.
[shortcuts]
# Nothing yet

# ─────────────────────────────────────────────
# Internal state
# ─────────────────────────────────────────────

[meta]

# Internal state managed by nx.
# Do not edit these values manually.

setup_done = true
"""

MISSING_FUTURE_SECTION = """# nx configuration
# This file contains user-configurable settings for nx.
# Changes to this file may affect how nx reads and writes your NixOS setup.


# ─────────────────────────────────────────────
# NixOS setup
# ─────────────────────────────────────────────


[setup]

configuration_path = "/etc/nixos/configuration.nix"

flake_enabled = false
flake_path = "/etc/nixos/flake.nix"

home_manager_enabled = false
home_manager_path = "/etc/nixos/home.nix"

unstable_variable = "unstable"

# ─────────────────────────────────────────────
# Internal state
# ─────────────────────────────────────────────

[meta]

# Internal state managed by nx.
# Do not edit these values manually.

setup_done = false
"""

CORRUPTED_TOML = """[setup
configuration_path = "/etc/nixos"
flake_enabled = true
"""

MISSING_SETUP_DONE = """# nx configuration
# This file contains user-configurable settings for nx.
# Changes to this file may affect how nx reads and writes your NixOS setup.


# ─────────────────────────────────────────────
# NixOS setup
# ─────────────────────────────────────────────


[setup]

configuration_path = "/etc/nixos/configuration.nix"

flake_enabled = false
flake_path = "/etc/nixos/flake.nix"

home_manager_enabled = false
home_manager_path = "/etc/nixos/home.nix"

unstable_variable = "unstable"

# ─────────────────────────────────────────────
# Future features
# ─────────────────────────────────────────────

[future]

# Features planned for future nx versions.
# These options are currently informational only.

# Remote Flake metadata registry.
# remote_registry = false

# Package file shortcuts.
[shortcuts]
# Nothing yet

# ─────────────────────────────────────────────
# Internal state
# ─────────────────────────────────────────────

[meta]

# Internal state managed by nx.
# Do not edit these values manually.
"""

INVALID_SETUP_DONE = """# nx configuration
# This file contains user-configurable settings for nx.
# Changes to this file may affect how nx reads and writes your NixOS setup.


# ─────────────────────────────────────────────
# NixOS setup
# ─────────────────────────────────────────────


[setup]

configuration_path = "/etc/nixos/configuration.nix"

flake_enabled = false
flake_path = "/etc/nixos/flake.nix"

home_manager_enabled = false
home_manager_path = "/etc/nixos/home.nix"

unstable_variable = "unstable"

# ─────────────────────────────────────────────
# Future features
# ─────────────────────────────────────────────

[future]

# Features planned for future nx versions.
# These options are currently informational only.

# Remote Flake metadata registry.
# remote_registry = false

# Package file shortcuts.
[shortcuts]
# Nothing yet

# ─────────────────────────────────────────────
# Internal state
# ─────────────────────────────────────────────

[meta]

# Internal state managed by nx.
# Do not edit these values manually.

setup_done = "maybe"
"""


# ─── Tests ─────────────────────────────────────────────────────────────────────

def test_validate_setup_value():
    """validate_setup_value correctly validates different value types"""
    assert validate_setup_value("configuration_path", "/etc/nixos")
    assert not validate_setup_value("configuration_path", "")
    
    assert validate_setup_value("flake_enabled", True)
    assert validate_setup_value("flake_enabled", False)
    assert not validate_setup_value("flake_enabled", "true")
    
    assert validate_setup_value("unstable_variable", "myPkgs")
    assert validate_setup_value("unstable_variable", "unstable")
    assert not validate_setup_value("unstable_variable", "")
    assert not validate_setup_value("unstable_variable", "123invalid")
    
    print("  ✓ validate_setup_value works correctly")


def test_create_fresh_config():
    """create_fresh_config creates file with all defaults and setup_done=false"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir) / ".config" / "nx"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "config.toml"
        
        with patch("core.config.CONFIG_DIR", config_dir), \
             patch("core.config.CONFIG_FILE", config_file):
            create_fresh_config()
            
            content = config_file.read_text()
            
            assert 'configuration_path = "/etc/nixos/configuration.nix"' in content
            assert "flake_enabled = false" in content
            assert 'unstable_variable = "unstable"' in content
            assert "setup_done = false" in content
            assert "[future]" in content
            assert "[shortcuts]" in content
            assert "[meta]" in content
    
    print("  ✓ create_fresh_config creates file with defaults and setup_done=false")


def test_validate_and_repair_preserves_valid_values():
    """validate_and_repair preserves valid user values"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_file = Path(tmpdir) / "config.toml"
        config_file.write_text(VALID_WITH_PKGS)
        
        with patch("core.config.CONFIG_DIR", Path(tmpdir)), \
             patch("core.config.CONFIG_FILE", config_file):
            validate_and_repair()
            
            content = config_file.read_text()
            
            # Valid values preserved
            assert 'configuration_path = "/custom/path/configuration.nix"' in content
            assert 'unstable_variable = "myPkgs"' in content
            assert "flake_enabled = true" in content
            assert "setup_done = true" in content
            
            # Fixed parts preserved
            assert "[future]" in content
            assert "[shortcuts]" in content
            assert "[meta]" in content
    
    print("  ✓ validate_and_repair preserves valid user values")


def test_validate_and_repair_adds_missing_keys():
    """validate_and_repair adds missing setup keys with defaults"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_file = Path(tmpdir) / "config.toml"
        config_file.write_text(MISSING_UNSTABLE_VAR)
        
        with patch("core.config.CONFIG_DIR", Path(tmpdir)), \
             patch("core.config.CONFIG_FILE", config_file):
            validate_and_repair()
            
            content = config_file.read_text()
            
            # Missing key added with default
            assert 'unstable_variable = "unstable"' in content
            
            # Existing values preserved
            assert 'configuration_path = "/custom/path/configuration.nix"' in content
            assert "setup_done = true" in content
    
    print("  ✓ validate_and_repair adds missing setup keys with defaults")


def test_validate_and_repair_restores_missing_sections():
    """validate_and_repair restores missing fixed sections like [future]"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_file = Path(tmpdir) / "config.toml"
        config_file.write_text(MISSING_FUTURE_SECTION)
        
        with patch("core.config.CONFIG_DIR", Path(tmpdir)), \
             patch("core.config.CONFIG_FILE", config_file):
            validate_and_repair()
            
            content = config_file.read_text()
            
            # Missing sections restored
            assert "[future]" in content
            assert "[shortcuts]" in content
            
            # Existing values preserved
            assert 'configuration_path = "/etc/nixos/configuration.nix"' in content
            assert "setup_done = false" in content
    
    print("  ✓ validate_and_repair restores missing fixed sections")


def test_validate_and_repair_handles_corrupted_toml():
    """validate_and_repair handles corrupted TOML gracefully"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_file = Path(tmpdir) / "config.toml"
        config_file.write_text(CORRUPTED_TOML)
        
        with patch("core.config.CONFIG_DIR", Path(tmpdir)), \
             patch("core.config.CONFIG_FILE", config_file):
            validate_and_repair()
            
            content = config_file.read_text()
            
            # File is repaired with defaults
            assert "[setup]" in content
            assert "[future]" in content
            assert "[shortcuts]" in content
            assert "[meta]" in content
            assert "setup_done = false" in content
    
    print("  ✓ validate_and_repair handles corrupted TOML")


def test_validate_and_repair_missing_setup_done():
    """validate_and_repair repairs missing setup_done to false"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_file = Path(tmpdir) / "config.toml"
        config_file.write_text(MISSING_SETUP_DONE)
        
        with patch("core.config.CONFIG_DIR", Path(tmpdir)), \
             patch("core.config.CONFIG_FILE", config_file):
            validate_and_repair()
            
            content = config_file.read_text()
            
            # setup_done added with false (safe default)
            assert "setup_done = false" in content
            
            # Other values preserved
            assert 'configuration_path = "/etc/nixos/configuration.nix"' in content
    
    print("  ✓ validate_and_repair repairs missing setup_done to false")


def test_validate_and_repair_invalid_setup_done():
    """validate_and_repair repairs invalid setup_done to false"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_file = Path(tmpdir) / "config.toml"
        config_file.write_text(INVALID_SETUP_DONE)
        
        with patch("core.config.CONFIG_DIR", Path(tmpdir)), \
             patch("core.config.CONFIG_FILE", config_file):
            validate_and_repair()
            
            content = config_file.read_text()
            
            # setup_done corrected to false
            assert "setup_done = false" in content
    
    print("  ✓ validate_and_repair repairs invalid setup_done to false")


def test_load_config_creates_fresh_if_missing():
    """load_config creates fresh config if file doesn't exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_file = Path(tmpdir) / "config.toml"
        
        with patch("core.config.CONFIG_DIR", Path(tmpdir)), \
             patch("core.config.CONFIG_FILE", config_file):
            result = load_config()
            
            assert config_file.exists()
            assert result["setup"]["configuration_path"] == "/etc/nixos/configuration.nix"
            assert result["meta"]["setup_done"] is False
    
    print("  ✓ load_config creates fresh config if missing")


def test_load_config_repairs_on_load():
    """load_config repairs config on load"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_file = Path(tmpdir) / "config.toml"
        config_file.write_text(MISSING_UNSTABLE_VAR)
        
        with patch("core.config.CONFIG_DIR", Path(tmpdir)), \
             patch("core.config.CONFIG_FILE", config_file):
            result = load_config()
            
            # Missing key repaired
            assert result["setup"]["unstable_variable"] == "unstable"
            
            # Valid values preserved
            assert result["setup"]["configuration_path"] == "/custom/path/configuration.nix"
            assert result["meta"]["setup_done"] is True
    
    print("  ✓ load_config repairs on load")


def test_mark_setup_complete():
    """mark_setup_complete sets setup_done to true"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_file = Path(tmpdir) / "config.toml"
        config_file.write_text(VALID_WITH_PKGS.replace("setup_done = true", "setup_done = false"))
        
        with patch("core.config.CONFIG_DIR", Path(tmpdir)), \
             patch("core.config.CONFIG_FILE", config_file):
            mark_setup_complete()
            
            content = config_file.read_text()
            assert "setup_done = true" in content
    
    print("  ✓ mark_setup_complete sets setup_done to true")


def test_is_setup_done():
    """is_setup_done reads setup_done correctly"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_file = Path(tmpdir) / "config.toml"
        
        with patch("core.config.CONFIG_DIR", Path(tmpdir)), \
             patch("core.config.CONFIG_FILE", config_file):
            # Missing file
            assert not is_setup_done()
            
            # setup_done = false
            config_file.write_text(VALID_WITH_PKGS.replace("setup_done = true", "setup_done = false"))
            assert not is_setup_done()
            
            # setup_done = true
            config_file.write_text(VALID_WITH_PKGS)
            assert is_setup_done()
            
            # Invalid setup_done
            config_file.write_text(INVALID_SETUP_DONE)
            assert not is_setup_done()
    
    print("  ✓ is_setup_done reads setup_done correctly")


if __name__ == "__main__":
    tests = [
        test_validate_setup_value,
        test_create_fresh_config,
        test_validate_and_repair_preserves_valid_values,
        test_validate_and_repair_adds_missing_keys,
        test_validate_and_repair_restores_missing_sections,
        test_validate_and_repair_handles_corrupted_toml,
        test_validate_and_repair_missing_setup_done,
        test_validate_and_repair_invalid_setup_done,
        test_load_config_creates_fresh_if_missing,
        test_load_config_repairs_on_load,
        test_mark_setup_complete,
        test_is_setup_done,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ {test.__name__}: {type(e).__name__}: {e}")
            failed += 1
    
    print(f"\n  {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
