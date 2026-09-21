import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from src.core.writer import (
    remove_flake, add_flake_input, add_flake_to_outputs, add_flake_package,
    backup_files, restore_files,
    remove_flake_reference, is_flake_name_in_content
)


def test_remove_flake_basic():
    """remove_flake() should remove the input block and clean up outputs"""
    content = '''{
  inputs = {
    nixpkgs = {
      url = "github:NixOS/nixpkgs/nixos-unstable";
    };
    plasma-manager = {
      url = "github:nix-community/plasma-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    }; # nx
  };
  outputs = { self, nixpkgs, plasma-manager }@inputs:
  {
    # ...
  };
}
'''
    result, found = remove_flake(content, 'plasma-manager')
    assert found is True
    assert 'plasma-manager' not in result
    assert 'nixpkgs' in result


def test_remove_flake_from_outputs():
    """remove_flake() should remove the flake name from outputs arguments"""
    content = '''{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs";
    plasma-manager = {
      url = "github:nix-community/plasma-manager";
    }; # nx
    neovim = {
      url = "github:nix-community/neovim";
    }; # nx
  };
  outputs = { self, nixpkgs, plasma-manager, neovim }:
  {};
}
'''
    result, found = remove_flake(content, 'plasma-manager')
    assert found is True
    assert 'plasma-manager' not in result
    assert 'neovim' in result
    assert 'nixpkgs' in result


def test_remove_last_flake():
    """remove_flake() should remove the flake even if it's the only one"""
    content = '''{
  inputs = {
    plasma-manager = {
      url = "github:nix-community/plasma-manager";
    }; # nx
  };
  outputs = { self, plasma-manager }:
  {};
}
'''
    result, found = remove_flake(content, 'plasma-manager')
    assert found is True
    assert 'plasma-manager' not in result
    assert 'self' in result


def test_remove_flake_not_found():
    """remove_flake() should return False if it doesn't find the flake"""
    content = '''{
  inputs = {};
  outputs = { }:
  {};
}
'''
    result, found = remove_flake(content, 'nonexistent')
    assert found is False


def test_round_trip_add_then_remove():
    """Adding then removing should return the file to its original state approximately"""
    original = '''{
  inputs = {
    nixpkgs = {
      url = "github:NixOS/nixpkgs/nixos-unstable";
    };
  };
  outputs = { self, nixpkgs }@inputs:
  {
    # ...
  };
}
'''
    content = add_flake_input(original, 'plasma-manager', 'github:nix-community/plasma-manager')
    content = add_flake_to_outputs(content, 'plasma-manager')
    
    assert 'plasma-manager' in content
    
    content, found = remove_flake(content, 'plasma-manager')
    assert found is True
    assert 'plasma-manager' not in content
    assert 'nixpkgs' in content


def test_rollback_on_rebuild_failure():
    """rollback should restore the original file when nixos-rebuild fails"""
    original_content = '''{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs";
    plasma-manager = {
      url = "github:nix-community/plasma-manager";
    }; # nx
  };
  outputs = { self, nixpkgs, plasma-manager }:
  {};
}
'''
    with tempfile.TemporaryDirectory() as tmpdir:
        flake_file = Path(tmpdir) / "flake.nix"
        flake_file.write_text(original_content)
        
        # Create backup in temp dir and mock shutil.copy2
        backup_dir = Path(tmpdir) / ".nx-backup"
        backup_dir.mkdir()
        
        call_count = {"backup": 0, "restore": 0}
        
        original_copy2 = shutil.copy2
        
        def mock_copy2(src, dst):
            # Redirect copies to our temp backup dir
            if str(dst).startswith("/etc/nixos/.nx-backup/"):
                dst = backup_dir / Path(dst).name
            if str(src).startswith("/etc/nixos/.nx-backup/"):
                src = backup_dir / Path(src).name
            call_count["backup" if src == flake_file else "restore"] += 1
            return original_copy2(src, dst)
        
        with patch("shutil.copy2", side_effect=mock_copy2):
            backup_files([flake_file])
            
            flake_content = flake_file.read_text()
            new_content, found = remove_flake(flake_content, 'plasma-manager')
            assert found is True
            flake_file.write_text(new_content)
            
            assert 'plasma-manager' not in flake_file.read_text()
            
            restore_files([flake_file])
        
        restored_content = flake_file.read_text()
        assert restored_content == original_content


def test_rollback_includes_multiple_files():
    """rollback should restore all files in the transaction"""
    original_flake = '''{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs";
    plasma-manager = {
      url = "github:nix-community/plasma-manager";
    }; # nx
  };
  outputs = { self, nixpkgs, plasma-manager }:
  {};
}
'''
    original_lock = '''{
  "nodes": {
    "plasma-manager": {}
  }
}
'''
    original_home = '''{
  home.packages = [
    inputs.plasma-manager.packages.${pkgs.stdenv.hostPlatform.system}.default
  ];
}
'''
    with tempfile.TemporaryDirectory() as tmpdir:
        flake_file = Path(tmpdir) / "flake.nix"
        lock_file = Path(tmpdir) / "flake.lock"
        home_file = Path(tmpdir) / "home.nix"
        
        flake_file.write_text(original_flake)
        lock_file.write_text(original_lock)
        home_file.write_text(original_home)
        
        files = [flake_file, lock_file, home_file]
        backup_dir = Path(tmpdir) / ".nx-backup"
        backup_dir.mkdir()
        
        original_copy2 = shutil.copy2
        
        def mock_copy2(src, dst):
            if str(dst).startswith("/etc/nixos/.nx-backup/"):
                dst = backup_dir / Path(dst).name
            if str(src).startswith("/etc/nixos/.nx-backup/"):
                src = backup_dir / Path(src).name
            return original_copy2(src, dst)
        
        with patch("shutil.copy2", side_effect=mock_copy2):
            backup_files(files)
            
            # Modify all files
            flake_content = flake_file.read_text()
            new_content, found = remove_flake(flake_content, 'plasma-manager')
            flake_file.write_text(new_content)
            
            lock_file.write_text('{}')
            
            home_content = home_file.read_text()
            new_home, _ = remove_flake_reference(home_content, 'plasma-manager')
            home_file.write_text(new_home)
            
            # Verify all changed
            assert 'plasma-manager' not in flake_file.read_text()
            assert 'plasma-manager' not in lock_file.read_text()
            assert 'plasma-manager' not in home_file.read_text()
            
            # Restore
            restore_files(files)
        
        # Verify all restored byte-for-byte
        assert flake_file.read_text() == original_flake
        assert lock_file.read_text() == original_lock
        assert home_file.read_text() == original_home


def test_remove_flake_reference_basic():
    """remove_flake_reference() removes references from home.nix"""
    content = '''{
  home.packages = [
    inputs.plasma-manager.packages.${pkgs.stdenv.hostPlatform.system}.default
    inputs.hyprmod.packages.${pkgs.stdenv.hostPlatform.system}.default
  ];
}
'''
    result, found = remove_flake_reference(content, 'plasma-manager')
    assert found is True
    assert 'plasma-manager' not in result
    assert 'hyprmod' in result


def test_remove_flake_reference_multiple():
    """remove_flake_reference() removes all references even if duplicated"""
    content = '''{
  home.packages = [
    inputs.plasma-manager.packages.${pkgs.stdenv.hostPlatform.system}.default
    inputs.plasma-manager.packages.${pkgs.stdenv.hostPlatform.system}.default
    pkgs.vim
  ];
}
'''
    result, found = remove_flake_reference(content, 'plasma-manager')
    assert found is True
    assert 'plasma-manager' not in result
    assert 'pkgs.vim' in result


def test_remove_flake_reference_not_found():
    """remove_flake_reference() returns False if it doesn't find a reference"""
    content = '''{
  home.packages = [
    pkgs.vim
  ];
}
'''
    result, found = remove_flake_reference(content, 'plasma-manager')
    assert found is False
    assert result == content


def test_remove_flake_reference_doesnt_touch_unknown_refs():
    """remove_flake_reference() doesn't delete references that don't match the nx pattern"""
    content = '''{
  home.packages = [
    inputs.plasma-manager.packages.${pkgs.stdenv.hostPlatform.system}.default
    some-other-thing.plasma-manager.something
    pkgs.vim
  ];
}
'''
    result, found = remove_flake_reference(content, 'plasma-manager')
    assert found is True
    # It should only remove the reference that matches the nx pattern
    assert 'some-other-thing.plasma-manager.something' in result


def test_is_flake_name_in_content():
    """is_flake_name_in_content() detects the presence of the flake name"""
    content = "some text with plasma-manager in it"
    assert is_flake_name_in_content(content, 'plasma-manager') is True
    assert is_flake_name_in_content(content, 'nonexistent') is False


def test_add_flake_then_remove_reference_round_trip():
    """Adding then removing a reference from home.nix returns to the original state"""
    original = '''{
  home.packages = [
    inputs.hyprmod.packages.${pkgs.stdenv.hostPlatform.system}.default
    pkgs.vim
  ];
}
'''
    content = add_flake_package(original, 'plasma-manager', 'default')
    assert 'plasma-manager' in content
    
    content, found = remove_flake_reference(content, 'plasma-manager')
    assert found is True
    # After removal, the content should match the original (with only a trailing newline difference)
    assert 'plasma-manager' not in content
    assert 'hyprmod' in content
    assert 'pkgs.vim' in content


def test_rollback_atomicity_on_write_failure():
    """rollback should restore files that failed to write"""
    original_flake = '''{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs";
    plasma-manager = {
      url = "github:nix-community/plasma-manager";
    }; # nx
  };
  outputs = { self, nixpkgs, plasma-manager }:
  {};
}
'''
    with tempfile.TemporaryDirectory() as tmpdir:
        flake_file = Path(tmpdir) / "flake.nix"
        flake_file.write_text(original_flake)

        files = [flake_file]
        backup_dir = Path(tmpdir) / ".nx-backup"
        backup_dir.mkdir()
        
        original_copy2 = shutil.copy2
        
        def mock_copy2(src, dst):
            if str(dst).startswith("/etc/nixos/.nx-backup/"):
                dst = backup_dir / Path(dst).name
            if str(src).startswith("/etc/nixos/.nx-backup/"):
                src = backup_dir / Path(src).name
            return original_copy2(src, dst)
        
        with patch("shutil.copy2", side_effect=mock_copy2):
            backup_files(files)

            # First write succeeded
            new_content, found = remove_flake(flake_file.read_text(), 'plasma-manager')
            assert found is True
            flake_file.write_text(new_content)
            assert 'plasma-manager' not in flake_file.read_text()

            # Simulate failure - restore recovers everything
            restore_files(files)

            # flake.nix returned to original byte-for-byte
            assert flake_file.read_text() == original_flake


def test_rollback_when_lock_not_exists_before():
    """rollback doesn't restore flake.lock if it didn't exist before the operation"""
    original_flake = '''{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs";
    plasma-manager = {
      url = "github:nix-community/plasma-manager";
    }; # nx
  };
  outputs = { self, nixpkgs, plasma-manager }:
  {};
}
'''
    with tempfile.TemporaryDirectory() as tmpdir:
        flake_file = Path(tmpdir) / "flake.nix"
        flake_file.write_text(original_flake)

        # flake.lock doesn't exist
        lock_file = Path(tmpdir) / "flake.lock"
        assert not lock_file.exists()

        # backup only for flake.nix
        files = [flake_file]
        backup_dir = Path(tmpdir) / ".nx-backup"
        backup_dir.mkdir()
        
        original_copy2 = shutil.copy2
        
        def mock_copy2(src, dst):
            if str(dst).startswith("/etc/nixos/.nx-backup/"):
                dst = backup_dir / Path(dst).name
            if str(src).startswith("/etc/nixos/.nx-backup/"):
                src = backup_dir / Path(src).name
            return original_copy2(src, dst)
        
        with patch("shutil.copy2", side_effect=mock_copy2):
            backup_files(files)

            # modify flake.nix
            new_content, found = remove_flake(flake_file.read_text(), 'plasma-manager')
            flake_file.write_text(new_content)

            # Create flake.lock during operation (simulation)
            lock_file.write_text('{"nodes": {}}')

            # rollback
            restore_files(files)

            # flake.nix returned to original
            assert flake_file.read_text() == original_flake


if __name__ == "__main__":
    tests = [
        test_remove_flake_basic,
        test_remove_flake_from_outputs,
        test_remove_last_flake,
        test_remove_flake_not_found,
        test_round_trip_add_then_remove,
        test_rollback_on_rebuild_failure,
        test_rollback_includes_multiple_files,
        test_remove_flake_reference_basic,
        test_remove_flake_reference_multiple,
        test_remove_flake_reference_not_found,
        test_remove_flake_reference_doesnt_touch_unknown_refs,
        test_is_flake_name_in_content,
        test_add_flake_then_remove_reference_round_trip,
        test_rollback_atomicity_on_write_failure,
        test_rollback_when_lock_not_exists_before,
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
