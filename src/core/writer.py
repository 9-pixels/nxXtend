import re
import shutil
from pathlib import Path
from src.models.package import Package

CONFIG_PATH = Path("/etc/nixos-test/configuration.nix")
BACKUP_PATH = Path("/etc/nixos-test/configuration.nix.bak")

def detect_format(content: str) -> str:
    if "import" in content and "systemPackages" in content:
        return "external"
    elif "with pkgs;" in content and "systemPackages" in content:
        return "with_pkgs"
    elif "systemPackages" in content and "pkgs." in content:
        return "explicit_pkgs"
    elif "systemPackages" in content:
        return "empty"
    else:
        return "missing"

def read_config() -> str:
    return CONFIG_PATH.read_text()

def detect_format(content: str) -> str:
    if re.search(r'systemPackages\s*=\s*import', content):
        return "external"
    elif re.search(r'systemPackages\s*=.*with pkgs;', content, re.DOTALL):
        return "with_pkgs"
    elif re.search(r'systemPackages\s*=\s*\[', content) and 'pkgs.' in content:
        return "explicit_pkgs"
    elif re.search(r'systemPackages\s*=\s*\[\s*\]', content):
        return "empty"
    elif 'systemPackages' not in content:
        return "missing"
    else:
        return "with_pkgs"  # افتراضي

def backup_config():
    shutil.copy2(CONFIG_PATH, BACKUP_PATH)

def restore_backup():
    shutil.copy2(BACKUP_PATH, CONFIG_PATH)

def backup_files(files: list[Path]):
    backup_dir = Path("/etc/nixos/.nx-backup")
    backup_dir.mkdir(exist_ok=True)
    for file in files:
        if file.exists():
            shutil.copy2(file, backup_dir / file.name)

def restore_files(files: list[Path]):
    backup_dir = Path("/etc/nixos/.nx-backup")
    for file in files:
        backup = backup_dir / file.name
        if backup.exists():
            shutil.copy2(backup, file)