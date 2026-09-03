import re
import shutil
from pathlib import Path
from src.models.package import Package

# Default config paths — should be read from ~/.config/nx/config.toml in production
CONFIG_PATH = Path("/etc/nixos-test/configuration.nix")
BACKUP_PATH = Path("/etc/nixos-test/configuration.nix.bak")


def detect_format(content: str) -> str:
    """Detect the format variant of the systemPackages block in configuration.nix."""
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

def read_config(path: Path) -> str:
    """Read the configuration file content."""
    return path.read_text()

def backup_config(path: Path):
    """Create a .nix.bak backup of the configuration file."""
    shutil.copy2(path, path.with_suffix('.nix.bak'))

def restore_backup():
    """Restore the configuration from the .nix.bak backup."""
    shutil.copy2(BACKUP_PATH, CONFIG_PATH)

def backup_files(files: list[Path]):
    """Backup multiple files to /etc/nixos/.nx-backup/."""
    backup_dir = Path("/etc/nixos/.nx-backup")
    backup_dir.mkdir(exist_ok=True)
    for file in files:
        if file.exists():
            shutil.copy2(file, backup_dir / file.name)

def restore_files(files: list[Path]):
    """Restore multiple files from /etc/nixos/.nx-backup/."""
    backup_dir = Path("/etc/nixos/.nx-backup")
    for file in files:
        backup = backup_dir / file.name
        if backup.exists():
            shutil.copy2(backup, file)

def add_package_with_pkgs(content: str, pkg_name: str) -> str:
    """Add a package to a file using `with pkgs; [..]` syntax."""
    match = re.search(r'systemPackages\s*=\s*with pkgs;\s*\[', content)
    if not match:
        return content
    
    # Track brackets to find the matching closing bracket
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
    """Add a package to a file using `pkgs.name` explicit syntax."""
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
    """Fill in an empty `systemPackages = []` block with the package."""
    match = re.search(r'systemPackages\s*=\s*\[\s*\]', content)
    if not match:
        return content
    
    # Replace [] with a list containing the package
    return content[:match.start()] + \
           f"environment.systemPackages = [\n    {pkg_name}\n  ]" + \
           content[match.end():]

def add_package_missing(content: str, pkg_name: str) -> str:
    """Create a new `environment.systemPackages` block when none exists."""
    last_brace = content.rfind('}')
    
    new_block = f"\n\n  environment.systemPackages = with pkgs; [\n    {pkg_name}\n  ];\n"
    
    if last_brace == -1:
        # No } found — append at the end
        return content + new_block
    
    return content[:last_brace] + new_block + content[last_brace:]

def add_package_external(content: str, pkg_name: str, config_dir: Path) -> str:
    """Handle the case where systemPackages is imported from an external file."""
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
    """Add a package to the configuration file using the detected format."""
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
    """Remove a package from the configuration file. Returns (new_content, found)."""
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
    """Check if a package name contains only valid characters."""
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', pkg_name))

def is_package_exists(content: str, pkg_name: str, config_dir: Path) -> bool:
    """Check if a package already exists in the configuration."""
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


def is_input_exists(content: str, flake_name: str) -> bool:
    """Check if a flake input already exists in flake.nix."""
    return bool(re.search(rf'{re.escape(flake_name)}\s*=\s*{{', content) or
                re.search(rf'{re.escape(flake_name)}\.url\s*=', content))

def add_flake_input(content: str, flake_name: str, flake_url: str, follows: bool = True) -> str:
    """Add a flake input to flake.nix inputs block."""
    match = re.search(r'inputs\s*=\s*\{', content)
    if not match:
        return content

    pos = match.end()
    depth = 1
    while pos < len(content) and depth > 0:
        if content[pos] == '{':
            depth += 1
        elif content[pos] == '}':
            depth -= 1
        pos += 1

    closing_pos = pos - 1

    if follows:
        new_input = f'\n    {flake_name} = {{\n      url = "{flake_url}";\n      inputs.nixpkgs.follows = "nixpkgs";\n    }};'
    else:
        new_input = f'\n    {flake_name}.url = "{flake_url}";'

    return content[:closing_pos] + new_input + "\n  " + content[closing_pos:]

def add_flake_to_outputs(content: str, flake_name: str) -> str:
    """Add a flake to the outputs destructuring in flake.nix."""
    match = re.search(r'outputs\s*=\s*\{([^}]*)\}', content)
    if not match:
        return content

    inner = match.group(1)

    if flake_name in inner:
        return content  # Already exists

    # Add before ...
    if '...' in inner:
        new_inner = inner.replace('...', f'{flake_name}, ...')
    else:
        new_inner = inner.rstrip() + f', {flake_name}'

    return content[:match.start(1)] + new_inner + content[match.end(1):]

def add_flake_package(content: str, flake_name: str, pkg_attr: str, system_var: str = "pkgs.stdenv.hostPlatform.system") -> str:
    """Add a flake package reference to the configuration (home.packages or systemPackages)."""
    pkg_line = f"inputs.{flake_name}.packages.${{{system_var}}}.{pkg_attr}"
    
    # Look for home.packages first
    match = re.search(r'home\.packages\s*=\s*\[', content)
    if match:
        # Track bracket depth to find the matching closing bracket
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
        return content[:closing_pos] + f"{indent}{pkg_line}\n" + content[closing_pos:]

    # If home.packages not found, look for systemPackages
    return add_package(content, pkg_line, Path("."))

def add_flake_module(content: str, flake_name: str, module_name: str) -> str:
    """Add a nixosModule reference to the modules list in flake.nix."""
    module_line = f"{flake_name}.nixosModules.{module_name}"
    
    # Look for modules = [
    match = re.search(r'modules\s*=\s*\[', content)
    if not match:
        return content
    
    # Track bracket depth to find the matching closing bracket
    pos = match.end()
    depth = 1
    while pos < len(content) and depth > 0:
        if content[pos] == '[':
            depth += 1
        elif content[pos] == ']':
            depth -= 1
        pos += 1
    
    closing_pos = pos - 1
    
    # Check that it doesn't already exist
    inner = content[match.end():closing_pos]
    if module_line in inner:
        return content
    
    lines = inner.split('\n')
    indent = "        "
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            indent = line[:len(line) - len(line.lstrip())]
            break
    
    return content[:closing_pos] + f"{indent}{module_line}\n" + content[closing_pos:]

def add_flake_overlay(content: str, flake_name: str, overlay_name: str) -> str:
    """Add an overlay reference to nixpkgs.overlays, creating it if needed."""
    overlay_line = f"{flake_name}.overlays.{overlay_name}"
    
    # Look for nixpkgs.overlays
    match = re.search(r'nixpkgs\.overlays\s*=\s*\[', content)
    if match:
        # Track bracket depth to find the matching closing bracket
        pos = match.end()
        depth = 1
        while pos < len(content) and depth > 0:
            if content[pos] == '[':
                depth += 1
            elif content[pos] == ']':
                depth -= 1
            pos += 1
        
        closing_pos = pos - 1
        inner = content[match.end():closing_pos]
        
        if overlay_line in inner:
            return content
        
        lines = inner.split('\n')
        indent = "    "
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith('#'):
                indent = line[:len(line) - len(line.lstrip())]
                break
        
        return content[:closing_pos] + f"{indent}{overlay_line}\n" + content[closing_pos:]
    
    # If nixpkgs.overlays not found, create it in configuration.nix
    last_brace = content.rfind('}')
    new_block = f"\n  nixpkgs.overlays = [\n    {overlay_line}\n  ];\n"
    return content[:last_brace] + new_block + content[last_brace:]

def add_flake(
    flake_content: str,
    flake_name: str,
    flake_url: str,
    pkg_attr: str,
    pkg_type: str,  # "package", "nixosModule", "overlay", "homeModule"
    module_name: str = "default",
    overlay_name: str = "default",
    home_content: str = None,
    follows: bool = True
) -> tuple[str, str | None]:
    """High-level function to add a flake input and reference to the appropriate file.
    
    flake_content: flake.nix content
    home_content: home.nix content (if exists)
    Returns: (modified_flake_content, modified_home_content_or_None)
    """
    # 1 — Add the input if it doesn't exist
    if not is_input_exists(flake_content, flake_name):
        flake_content = add_flake_input(flake_content, flake_name, flake_url, follows)
        flake_content = add_flake_to_outputs(flake_content, flake_name)

    # 2 — Add based on type
    if pkg_type == "package":
        if home_content is not None:
            home_content = add_flake_package(home_content, flake_name, pkg_attr)
        else:
            flake_content = add_flake_package(flake_content, flake_name, pkg_attr)

    elif pkg_type == "nixosModule":
        flake_content = add_flake_module(flake_content, flake_name, module_name)

    elif pkg_type == "overlay":
        # overlay is added to configuration.nix, not flake.nix
        # return None for home_content and let main.py handle configuration.nix
        pass

    elif pkg_type == "homeModule":
        if home_content is not None:
            home_content = add_home_flake_module(home_content, flake_name, module_name)

    return flake_content, home_content
