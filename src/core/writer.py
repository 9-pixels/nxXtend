import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from src.models.package import Package


@dataclass
class AddResult:
    """Result of an add_package operation.
    
    Using this class instead of a plain string lets callers distinguish between
    a successful modification and a failure. Returning a raw string would force
    callers to either catch exceptions or compare content to detect failure,
    neither of which is ergonomic or safe.
    """
    content: str
    status: str


def detect_format(content: str, block: str = "environment.systemPackages") -> str:
    """Detect the format variant of a package block.

    `block` is the full attribute path of the package list, e.g.
    "environment.systemPackages" or "home.packages". Default preserves
    the historical systemPackages-only behavior.
    """
    b = re.escape(block)
    if re.search(rf'{b}\s*=\s*import', content):
        return "external"
    elif re.search(rf'{b}\s*=.*with pkgs;', content, re.DOTALL):
        return "with_pkgs"
    elif re.search(rf'{b}\s*=\s*\[', content) and 'pkgs.' in content:
        return "explicit_pkgs"
    elif re.search(rf'{b}\s*=\s*\[\s*\]', content):
        return "empty"
    elif block not in content:
        return "missing"
    else:
        return "with_pkgs"  # default


def read_config(path: Path) -> str:
    """Read the configuration file content."""
    return path.read_text()


def backup_files(files: list[Path], backup_dir: Path | None = None):
    """Backup multiple files. Defaults to /etc/nixos/.nx-backup/"""
    # All nx operations that modify Nix files go through this single backup path.
    # This keeps recovery simple: every file touched by a transaction lives in one
    # known location, so rollback always knows where to find the original content.
    if backup_dir is None:
        backup_dir = Path("/etc/nixos/.nx-backup")
    backup_dir.mkdir(exist_ok=True)
    for file in files:
        if file.exists():
            shutil.copy2(file, backup_dir / file.name)


def restore_files(files: list[Path], backup_dir: Path | None = None):
    """Restore multiple files. Defaults to /etc/nixos/.nx-backup/"""
    # This is the counterpart to backup_files. It is intentionally conservative:
    # if no backup exists for a file, we silently skip it. This matters for
    # flake.lock, which may not exist before the first flake operation but is
    # created by nix itself during the rebuild. Restoring a non-existent lock
    # file is correct — it means we simply don't have an original to revert to.
    if backup_dir is None:
        backup_dir = Path("/etc/nixos/.nx-backup")
    for file in files:
        backup = backup_dir / file.name
        if backup.exists():
            shutil.copy2(backup, file)


def add_package_with_pkgs(content: str, pkg_name: str, block: str = "environment.systemPackages") -> str:
    """Add a package to a block using `with pkgs; [..]` syntax."""
    match = re.search(rf'{re.escape(block)}\s*=\s*with pkgs;\s*\[', content)
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
    
    return content[:closing_pos] + f"{indent}{pkg_name}\n" + content[closing_pos:]


def add_package_explicit_pkgs(content: str, pkg_name: str, block: str = "environment.systemPackages") -> str:
    """Add a package to a block using explicit syntax (caller provides full reference)."""
    match = re.search(rf'{re.escape(block)}\s*=\s*\[', content)
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


def add_package_empty(content: str, pkg_name: str, block: str = "environment.systemPackages") -> str:
    """Fill in an empty `block = []` list with the package."""
    match = re.search(rf'{re.escape(block)}\s*=\s*\[\s*\]', content)
    if not match:
        return content
    
    return content[:match.start()] + \
           f"{block} = [\n    {pkg_name}\n  ]" + \
           content[match.end():]


def add_package_missing(content: str, pkg_name: str, block: str = "environment.systemPackages") -> str:
    """Create a new package block when none exists."""
    last_brace = content.rfind('}')
    
    new_block = f"\n\n  {block} = with pkgs; [\n    {pkg_name}\n  ];\n"
    
    if last_brace == -1:
        return content + new_block
    
    return content[:last_brace] + new_block + content[last_brace:]


def add_package_external(content: str, pkg_name: str, config_dir: Path, block: str = "environment.systemPackages") -> str:
    """Handle the case where the package block is imported from an external file."""
    match = re.search(rf'{re.escape(block)}\s*=\s*import\s+(\.\/\S+)', content)
    if not match:
        return content
    
    external_path = config_dir / match.group(1).lstrip('./')
    external_content = external_path.read_text()
    
    if re.search(r'with pkgs;', external_content):
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


def add_package(content: str, pkg_name: str, config_dir: Path, block: str = "environment.systemPackages") -> AddResult:
    """Add a package to a package block using the detected format."""
    fmt = detect_format(content, block)
    
    try:
        if fmt == "with_pkgs":
            return AddResult(content=add_package_with_pkgs(content, pkg_name, block), status="success")
        elif fmt == "explicit_pkgs":
            return AddResult(content=add_package_explicit_pkgs(content, pkg_name, block), status="success")
        elif fmt == "empty":
            return AddResult(content=add_package_with_pkgs(content, pkg_name, block), status="success")
        elif fmt == "missing":
            return AddResult(content=add_package_missing(content, pkg_name, block), status="success")
        elif fmt == "external":
            return AddResult(content=add_package_external(content, pkg_name, config_dir, block), status="success")
        else:
            return AddResult(content=content, status="unsupported_unknown")
    except Exception:
        return AddResult(content=content, status="error")


def remove_package(content: str, pkg_name: str, config_dir: Path, block: str = "environment.systemPackages") -> tuple[str, bool]:
    """Remove a package from a package block. Returns (new_content, found)."""
    fmt = detect_format(content, block)
    
    if fmt == "external":
        match = re.search(rf'{re.escape(block)}\s*=\s*import\s+(\.\/\S+)', content)
        if not match:
            return content, False
        external_path = config_dir / match.group(1).lstrip('./')
        ext_content = external_path.read_text()
        new_ext, found = remove_package(ext_content, pkg_name, external_path.parent, block)
        if found:
            external_path.write_text(new_ext)
        return content, found
    
    if fmt == "missing":
        return content, False
    
    if fmt == "with_pkgs":
        match = re.search(rf'{re.escape(block)}\s*=\s*with pkgs;\s*\[', content)
    else:
        match = re.search(rf'{re.escape(block)}\s*=\s*\[', content)
    
    if not match:
        return content, False
    
    pos = match.end()
    depth = 1
    while pos < len(content) and depth > 0:
        if content[pos] == '[': depth += 1
        elif content[pos] == ']': depth -= 1
        pos += 1
    
    start = match.end()
    end = pos - 1
    
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


def is_package_exists(content: str, pkg_name: str, config_dir: Path, block: str = "environment.systemPackages") -> bool:
    """Check if a package already exists in a package block."""
    fmt = detect_format(content, block)
    
    if fmt == "missing" or fmt == "empty":
        return False
    
    if fmt == "external":
        match = re.search(rf'{re.escape(block)}\s*=\s*import\s+(\.\/\S+)', content)
        if not match:
            return False
        external_path = config_dir / match.group(1).lstrip('./')
        return is_package_exists(external_path.read_text(), pkg_name, external_path.parent, block)
    
    if fmt == "with_pkgs":
        match = re.search(rf'{re.escape(block)}\s*=\s*with pkgs;\s*\[', content)
    else:
        match = re.search(rf'{re.escape(block)}\s*=\s*\[', content)
    
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


def add_flake_input(content: str, flake_name: str, flake_url: str, follows: bool = True, dep_of: str = None) -> str:
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
    
    if dep_of:
        new_input = f'\n    {flake_name}.url = "{flake_url}"; # nx-dep: {dep_of}'
    elif follows:
        new_input = f'\n    {flake_name} = {{\n      url = "{flake_url}";\n      inputs.nixpkgs.follows = "nixpkgs";\n    }}; # nx'
    else:
        new_input = f'\n    {flake_name}.url = "{flake_url}"; # nx'
    
    return content[:closing_pos] + new_input + "\n  " + content[closing_pos:]


def add_flake_to_outputs(content: str, flake_name: str) -> str:
    """Add a flake to the outputs destructuring in flake.nix."""
    match = re.search(r'outputs\s*=\s*\{([^}]*)\}', content)
    if not match:
        return content
    
    inner = match.group(1)
    
    if flake_name in inner:
        return content
    
    if '...' in inner:
        new_inner = inner.replace('...', f'{flake_name}, ...')
    else:
        new_inner = inner.rstrip() + f', {flake_name}'
    
    return content[:match.start(1)] + new_inner + content[match.end(1):]


def add_flake_package(content: str, flake_name: str, pkg_attr: str, system_var: str = "pkgs.stdenv.hostPlatform.system", block: str | None = None) -> str:
    """Add a flake package reference to a package block.

    block=None → auto-detect (home.packages first, then systemPackages).
    block="home.packages" / "environment.systemPackages" → target that
    block explicitly; if it is missing, create it instead of falling
    back to another file's block.
    """
    pkg_line = f"inputs.{flake_name}.packages.${{{system_var}}}.{pkg_attr}"

    if block is not None:
        # Explicit target block: use the target-aware add_package, which
        # handles all formats (with pkgs / explicit / empty / missing) and
        # creates the block when absent — never falls back elsewhere.
        result = add_package(content, pkg_line, Path("."), block)
        return result.content

    # Auto-detect (legacy): home.packages first — both `= with pkgs; [` and plain `= [` forms.
    match = re.search(r'home\.packages\s*=\s*(?:with pkgs;\s*)?\[', content)
    if match:
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
    
    result = add_package(content, pkg_line, Path("."))
    return result.content


def add_flake_module(content: str, flake_name: str, module_name: str) -> str:
    """Add a nixosModule reference to the modules list in flake.nix."""
    module_line = f"{flake_name}.nixosModules.{module_name}"
    
    match = re.search(r'modules\s*=\s*\[', content)
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
    """Add an overlay reference to nixpkgs.overlays, creating it if needed.

    The reference uses the `inputs.` namespace: the overlay line is written
    into configuration.nix/home.nix, where only `inputs.<name>` is in scope
    (via specialArgs), never the bare flake name.
    """
    overlay_line = f"inputs.{flake_name}.overlays.{overlay_name}"
    
    match = re.search(r'nixpkgs\.overlays\s*=\s*\[', content)
    if match:
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
    
    last_brace = content.rfind('}')
    new_block = f"\n  nixpkgs.overlays = [\n    {overlay_line}\n  ];\n"
    return content[:last_brace] + new_block + content[last_brace:]


def add_flake(
    flake_content: str,
    flake_name: str,
    flake_url: str,
    pkg_attr: str,
    pkg_type: str,
    module_name: str = "default",
    overlay_name: str = "default",
    home_content: str = None,
    follows: bool = True,
    block: str | None = None,
) -> tuple[str, str | None]:
    """High-level function to add a flake input and reference.

    The input declaration always goes to flake_content (flake.nix); the
    package reference goes to home_content (the selected target file)
    when provided, else into flake_content. `block` names the package
    block inside the target file; None keeps legacy auto-detection.
    """
    if not is_input_exists(flake_content, flake_name):
        flake_content = add_flake_input(flake_content, flake_name, flake_url, follows)
        flake_content = add_flake_to_outputs(flake_content, flake_name)
    
    if pkg_type == "package":
        if home_content is not None:
            home_content = add_flake_package(home_content, flake_name, pkg_attr, block=block)
        else:
            flake_content = add_flake_package(flake_content, flake_name, pkg_attr, block=block)
    elif pkg_type == "nixosModule":
        flake_content = add_flake_module(flake_content, flake_name, module_name)
    elif pkg_type == "overlay":
        pass
    elif pkg_type == "homeModule":
        if home_content is not None:
            home_content = add_home_flake_module(home_content, flake_name, module_name)
    
    return flake_content, home_content


def remove_flake(content: str, flake_name: str) -> tuple[str, bool]:
    """Remove a flake input and its outputs reference added by nx."""
    removed = False
    
    lines = content.split('\n')
    new_lines = [l for l in lines if f'# nx-dep: {flake_name}' not in l]
    content = '\n'.join(new_lines)

    match = re.search(
        rf'\n\s*{re.escape(flake_name)}\s*=\s*\{{[^}}]*\}};\s*#\s*nx\b',
        content, re.DOTALL
    )
    if match:
        content = content[:match.start()] + content[match.end():]
        removed = True
    else:
        match = re.search(
            rf'\n\s*{re.escape(flake_name)}\.url\s*=\s*"[^"]*";\s*#\s*nx\b',
            content
        )
        if match:
            content = content[:match.start()] + content[match.end():]
            removed = True

    if not removed:
        return content, False

    outputs_match = re.search(
        r'outputs\s*=\s*\{([^}]*)\}',
        content
    )
    if outputs_match:
        inner = outputs_match.group(1)
        entries = [e.strip() for e in inner.split(',') if e.strip() and e.strip() != flake_name]
        cleaned = ', '.join(entries)
        if not cleaned.strip():
            cleaned = '...'
        content = content[:outputs_match.start(1)] + cleaned + content[outputs_match.end(1):]

    return content, True


def remove_flake_reference(content: str, flake_name: str) -> tuple[str, bool]:
    """Remove a flake package/overlay reference from a target file.

    Matches the references nx generates:
      inputs.<name>.packages.${<system>}.<attr>   (packages)
      inputs.<name>.overlays.<attr>              (overlays)
    """
    escaped = re.escape(flake_name)
    patterns = [
        rf'^\s*inputs\.{escaped}\.packages\.\$\{{[^}}]+\}}\.\S+\s*$',
        rf'^\s*inputs\.{escaped}\.overlays\.\S+\s*$',
    ]
    lines = content.split('\n')
    new_lines = []
    found = False
    for line in lines:
        if any(re.match(p, line) for p in patterns):
            found = True
            continue
        new_lines.append(line)
    return '\n'.join(new_lines), found


def is_flake_name_in_content(content: str, flake_name: str) -> bool:
    """Check if flake_name appears anywhere in content."""
    return flake_name in content


def build_package_reference(name: str, source: str, fmt: str, unstable_var: str = "unstable") -> str:
    """Build the final Nix reference for a package based on source and format."""
    if source == "unstable":
        ref = f"{unstable_var}.{name}"
    elif fmt == "explicit_pkgs":
        ref = f"pkgs.{name}"
    else:
        ref = name
    return ref
