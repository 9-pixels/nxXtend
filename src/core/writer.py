import re
import shutil
from pathlib import Path
from src.models.package import Package

CONFIG_PATH = Path("/etc/nixos-test/configuration.nix")
BACKUP_PATH = Path("/etc/nixos-test/configuration.nix.bak")


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
        return "with_pkgs"  # default

def read_config() -> str:
    return CONFIG_PATH.read_text()

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

def add_package_with_pkgs(content: str, pkg_name: str) -> str:
    match = re.search(r'systemPackages\s*=\s*with pkgs;\s*\[', content)
    if not match:
        return content
    
    # Track brackets to find the correct closing
    pos = match.end()
    depth = 1
    while pos < len(content) and depth > 0:
        if content[pos] == '[':
            depth += 1
        elif content[pos] == ']':
            depth -= 1
        pos += 1
    
    closing_pos = pos - 1
    
    # Detect indentation from existing packages
    lines = content[match.end():closing_pos].split('\n')
    indent = "    "
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            indent = line[:len(line) - len(line.lstrip())]
            break
    
    return content[:closing_pos] + f"{indent}{pkg_name}\n" + content[closing_pos:]

def add_package_explicit_pkgs(content: str, pkg_name: str) -> str:
    match = re.search(r'systemPackages\s*=\s*\[', content)
    if not match:
        return content
    
    pos = match.end()
    depth = 1
    while pos < len(content) and depth > 0:
        if content[pos] == '[':
            depth += 1
        elif content[pos] == ']':
            depth -= 1
        pos += 1
    
    closing_pos = pos - 1
    
    lines = content[match.end():closing_pos].split('\n')
    indent = "    "
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            indent = line[:len(line) - len(line.lstrip())]
            break
    
    return content[:closing_pos] + f"{indent}pkgs.{pkg_name}\n" + content[closing_pos:]

def add_package_empty(content: str, pkg_name: str) -> str:
    match = re.search(r'systemPackages\s*=\s*\[\s*\]', content)
    if not match:
        return content
    
    # Replace [] with a list containing the package
    return content[:match.start()] + \
           f"environment.systemPackages = [\n    {pkg_name}\n  ]" + \
           content[match.end():]

def add_package_missing(content: str, pkg_name: str) -> str:
    last_brace = content.rfind('}')
    
    new_block = f"\n\n  environment.systemPackages = with pkgs; [\n    {pkg_name}\n  ];\n"
    
    if last_brace == -1:
        # No } found — append at the end
        return content + new_block
    
    return content[:last_brace] + new_block + content[last_brace:]

def add_package_external(content: str, pkg_name: str, config_dir: Path) -> str:
    match = re.search(r'systemPackages\s*=\s*import\s+(\.\/\S+)', content)
    if not match:
        return content
    
    external_path = config_dir / match.group(1).lstrip('./')
    external_content = external_path.read_text()
    
    # Detect the format of the external file
    if re.search(r'with pkgs;', external_content):
        # Find the last ] and insert before it
        closing_pos = external_content.rfind(']')
        if closing_pos == -1:
            return content
        lines = external_content[:closing_pos].split('\n')
        indent = "  "
        for line in reversed(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith('#'):
                indent = line[:len(line) - len(line.lstrip())]
                break
        new_external = external_content[:closing_pos] + f"{indent}{pkg_name}\n" + external_content[closing_pos:]
    elif re.search(r'pkgs\.', external_content):
        closing_pos = external_content.rfind(']')
        if closing_pos == -1:
            return content
        new_external = external_content[:closing_pos] + f"  pkgs.{pkg_name}\n" + external_content[closing_pos:]
    else:
        print("External file format unknown")
        return content
    
    external_path.write_text(new_external)
    return content

def add_package(content: str, pkg_name: str, config_dir: Path) -> str:
    fmt = detect_format(content)
    
    if fmt == "with_pkgs":
        return add_package_with_pkgs(content, pkg_name)
    elif fmt == "explicit_pkgs":
        return add_package_explicit_pkgs(content, pkg_name)
    elif fmt == "empty":
        return add_package_with_pkgs(content, pkg_name)  # same logic
    elif fmt == "missing":
        return add_package_missing(content, pkg_name)
    elif fmt == "external":
        return add_package_external(content, pkg_name, config_dir)
    else:
        print("Could not detect file format — add the package manually")
        return content

def remove_package(content: str, pkg_name: str, config_dir: Path) -> tuple[str, bool]:
    fmt = detect_format(content)
    
    if fmt == "external":
        # Follow the external file
        match = re.search(r'systemPackages\s*=\s*import\s+(\.\/\S+)', content)
        if not match:
            return content, False
        external_path = config_dir / match.group(1).lstrip('./')
        ext_content = external_path.read_text()
        new_ext, found = remove_package(ext_content, pkg_name, external_path.parent)
        if found:
            external_path.write_text(new_ext)
        return content, found
    
    if fmt == "missing":
        return content, False
    
    # Locate the systemPackages range
    if fmt == "with_pkgs":
        match = re.search(r'systemPackages\s*=\s*with pkgs;\s*\[', content)
    else:
        match = re.search(r'systemPackages\s*=\s*\[', content)
    
    if not match:
        return content, False
    
    # Find the end of the range by tracking brackets
    pos = match.end()
    depth = 1
    while pos < len(content) and depth > 0:
        if content[pos] == '[': depth += 1
        elif content[pos] == ']': depth -= 1
        pos += 1
    
    start = match.end()
    end = pos - 1
    
    # Only modify within the range
    inner = content[start:end]
    lines = inner.split('\n')
    new_lines = []
    found = False
    
    for line in lines:
        stripped = line.strip()
        if stripped == pkg_name or stripped == f"pkgs.{pkg_name}":
            found = True
            continue
        new_lines.append(line)
    
    new_inner = '\n'.join(new_lines)
    return content[:start] + new_inner + content[end:], found

def is_valid_name(pkg_name: str) -> bool:
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', pkg_name))
def is_package_exists(content: str, pkg_name: str, config_dir: Path) -> bool:
    fmt = detect_format(content)
    
    if fmt == "missing" or fmt == "empty":
        return False
    
    if fmt == "external":
        match = re.search(r'systemPackages\s*=\s*import\s+(\.\/\S+)', content)
        if not match:
            return False
        external_path = config_dir / match.group(1).lstrip('./')
        return is_package_exists(external_path.read_text(), pkg_name, external_path.parent)
    
    if fmt == "with_pkgs":
        match = re.search(r'systemPackages\s*=\s*with pkgs;\s*\[', content)
    else:
        match = re.search(r'systemPackages\s*=\s*\[', content)
    
    if not match:
        return False
    
    pos = match.end()
    depth = 1
    while pos < len(content) and depth > 0:
        if content[pos] == '[': depth += 1
        elif content[pos] == ']': depth -= 1
        pos += 1
    
    inner = content[match.end():pos - 1]
    
    for line in inner.split('\n'):
        stripped = line.strip()
        if stripped == pkg_name or stripped == f"pkgs.{pkg_name}":
            return True
    
    return False
