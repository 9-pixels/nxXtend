"""Backup and restore isolation tests.

Every call passes an explicit ``backup_dir`` from the shared fixture, which
lives under ``tmp_path``. The writer's production default
(``/etc/nixos/.nx-backup``) is a root-owned system directory that does not
exist on a CI runner — even ``mkdir(exist_ok=True)`` there would fail.
"""
from unittest.mock import patch

from core.writer import backup_files, restore_files


def test_backup_creates_backup_dir(tmp_path, backup_dir):
    """backup_files() copies an existing file into the isolated dir."""
    test_file = tmp_path / "test.nix"
    test_file.write_text("content")

    with patch("core.writer.shutil.copy2") as mock_copy:
        backup_files([test_file], backup_dir=backup_dir)

    mock_copy.assert_called_once()
    assert mock_copy.call_args[0][0] == test_file
    assert mock_copy.call_args[0][1] == backup_dir / "test.nix"


def test_backup_with_missing_file(tmp_path, backup_dir):
    """backup_files() ignores a source that does not exist."""
    missing_file = tmp_path / "nonexistent.nix"

    with patch("core.writer.shutil.copy2") as mock_copy:
        backup_files([missing_file], backup_dir=backup_dir)

    mock_copy.assert_not_called()


def test_restore_from_backup(tmp_path, backup_dir):
    """restore_files() copies the saved content back from the isolated dir."""
    test_file = tmp_path / "test.nix"
    original = "original content"
    (backup_dir / "test.nix").write_text(original)
    test_file.write_text("modified content")

    restore_files([test_file], backup_dir=backup_dir)

    assert test_file.read_text() == original


def test_restore_with_missing_backup(tmp_path, backup_dir):
    """restore_files() ignores a file that has no backup."""
    test_file = tmp_path / "test.nix"
    test_file.write_text("content")

    with patch("core.writer.shutil.copy2") as mock_copy:
        restore_files([test_file], backup_dir=backup_dir)

    mock_copy.assert_not_called()
