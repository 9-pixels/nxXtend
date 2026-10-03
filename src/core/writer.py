import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from models.package import Package


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


@dataclass
class PackageIdentity:
    """Canonical identity of a package, separating the user-facing name
    from the source it came from and the precise reference used in the Nix
    configuration.

    This is the single abstraction that lets the install/remove logic
    reason about the same package name from different sources:

        name:        "htop"
        source:      "stable" | "unstable"
        reference:   "htop"           (stable, with_pkgs fmt)
                     "pkgs.htop"      (stable, explicit fmt)
                     "unstable.htop"  (unstable, with pkgs.<var> prefix)

    Two references are considered the *same identity* only when both their
    package name AND source match.
    """
    name: str
    source: str
    reference: str


def resolve_identity(pkg_name: str, source: str = "stable",
                     unstable_var: str = "unstable") -> PackageIdentity:
    """Build a PackageIdentity from a raw user string + source.

    Handles:
      * bare name     "htop"           → stable reference, normalized per fmt
      * prefixed name "unstable.htop"  → unstable reference (respects unstable_var)
      * full explicit "pkgs.htop"      → treated as stable, name = "htop"

    Never produces a doubled prefix like ``"pkgs.pkgs.htop"``: a bare name
    only receives ``pkgs.`` when written into an explicit_pkgs block, by
    add_package_explicit_pkgs — the identity layer never blindly prepends.
    """
    if source == "unstable":
        if pkg_name.startswith(f"{unstable_var}."):
            name = pkg_name[len(unstable_var) + 1:]
        else:
            name = pkg_name
        return PackageIdentity(name=name, source="unstable",
                               reference=f"{unstable_var}.{name}")
    # source == "stable": a bare name (e.g. "htop") is the canonical stable
    # reference for a `with pkgs;` block; "pkgs.htop" is the canonical stable
    # reference for an explicit block.  We do NOT carry an unstable_var prefix
    # here — that would mix sources.  If the caller passed an unstable
    # reference with source="stable", that is a caller bug; we still produce a
    # consistent stable identity by stripping any unstable_var prefix.
    name = pkg_name
    if name.startswith(f"{unstable_var}."):
        name = name[len(unstable_var) + 1:]
    name = name[len("pkgs."):] if name.startswith("pkgs.") else name
    return PackageIdentity(name=name, source="stable", reference=name)


SUPPORTED_FORMATS = {"with_pkgs", "explicit_pkgs"}
"""The only package-list formats nx may modify automatically in Beta.

detect_format() detects all six variants; this set is the single
authority deciding which of them may be mutated. Nothing else in the
codebase may make a support decision on its own.
"""


def _skip_ws_and_comments(content: str, pos: int) -> int:
    """Advance pos past whitespace and whole-line/trailing # comments."""
    n = len(content)
    while pos < n:
        ch = content[pos]
        if ch in " \t\r\n":
            pos += 1
        elif ch == "#":
            nl = content.find("\n", pos)
            pos = n if nl == -1 else nl + 1
        else:
            break
    return pos


def _find_list_end(content: str, open_pos: int) -> int | None:
    """Return the index of the `]` matching the `[` at open_pos, or None.

    Deliberately limited: `#` comments and double-quoted strings are
    skipped so brackets inside them cannot confuse the depth count.
    Interpolations inside strings (`${ ... }`) are not parsed — that
    would require a real Nix parser (documented limitation).
    """
    depth = 1
    pos = open_pos + 1
    n = len(content)
    while pos < n:
        ch = content[pos]
        if ch == "#":
            nl = content.find("\n", pos)
            pos = n if nl == -1 else nl + 1
            continue
        if ch == '"':
            close = content.find('"', pos + 1)
            if close == -1:
                return None
            pos = close + 1
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return pos
        pos += 1
    return None


def detect_format(content: str, block: str = "environment.systemPackages") -> str:
    """Detect the format variant of a package block.

    `block` is the full attribute path of the package list, e.g.
    "environment.systemPackages" or "home.packages". Default preserves
    the historical systemPackages-only behavior.

    Detection is scoped to the requested block only: the declaration is
    anchored to a line start (so comments mentioning the block name are
    skipped) and everything examined afterwards belongs to that same
    declaration — a `with pkgs;` appearing later in the file, inside an
    unrelated block, can never influence the result.
    """
    b = re.escape(block)
    # Find the declaration, but skip any occurrence that lives inside a
    # `#` comment on its line (so a block name mentioned only in a comment
    # or string is not mistaken for a real attribute assignment).
    decl = None
    for m in re.finditer(rf'{b}\s*=', content):
        line_start = content.rfind('\n', 0, m.start()) + 1
        up_to = content[line_start:m.start()]
        if not (up_to.lstrip().startswith('#') or '#' in up_to):
            decl = m
            break
    if not decl:
        return "missing"

    # Advance past whitespace/comments only. Anything else before the
    # value means the declaration is malformed or another assignment
    # begins here — never skip over it into an unrelated block.
    val_pos = _skip_ws_and_comments(content, decl.end())
    if val_pos >= len(content):
        return "unknown"
    after = content[val_pos:]

    if re.match(r'\bimport\b', after):
        return "external"

    with_match = re.match(r'with\s+pkgs\s*;\s*\[', after)
    if with_match:
        open_pos = val_pos + with_match.end() - 1
    else:
        list_match = re.match(r'\[', after)
        if not list_match:
            # Block exists but its value is not a plain list (mkMerge, lib.*, ...)
            return "unknown"
        open_pos = val_pos + list_match.end() - 1
    close_pos = _find_list_end(content, open_pos)
    if close_pos is None:
        return "unknown"
    if not content[close_pos + 1:].lstrip().startswith(";"):
        # The list is part of a larger expression (e.g. `[ a ] ++ [ b ]`)
        return "unknown"

    inner = content[open_pos + 1:close_pos]
    if not inner.strip():
        return "empty"
    if with_match:
        return "with_pkgs"
    if re.search(r'\bpkgs\.', inner):
        return "explicit_pkgs"
    return "unknown"


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
    """Add a package to a block using `with pkgs; [..]` syntax.

    Returns content unchanged if ``pkg_name`` is already present as an
    exact line entry (after stripping trailing comments) — this is the
    defense-in-depth duplicate check that backs up `add_package`'s
    `no_change` detection.  The caller (`add_package`) is also expected
    to have performed pre-validation.
    """
    match = re.search(rf'{re.escape(block)}\s*=\s*with\s+pkgs\s*;\s*\[', content)
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

    # C1 defense-in-depth: don't insert a duplicate. Normalize the token
    # we are about to add so "pkgs.htop" and "htop" are both recognized
    # as the same entry.
    for line in content[match.end():closing_pos].split('\n'):
        code = line.strip().split('#')[0].strip()
        if code == pkg_name or code == pkg_name.replace("pkgs.", "", 1) or code == f"pkgs.{pkg_name.replace('pkgs.', '', 1)}":
            return content

    lines = content[match.end():closing_pos].split('\n')
    indent = "    "
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            indent = line[:len(line) - len(line.lstrip())]
            break

    # Normalize: inside "with pkgs;" the bare name is the canonical form.
    # "pkgs.htop" -> "htop", bare "htop" stays "htop".
    identity = resolve_identity(pkg_name, source="stable")
    ref = identity.reference

    return content[:closing_pos] + f"{indent}{ref}\n" + content[closing_pos:]


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

    # Normalize the reference: bare names get the pkgs. prefix; already
    # qualified references (pkgs.vim, unstable.vim, inputs.*....vim)
    # must never be double-prefixed. Strip a leading "pkgs." first so we
    # never produce "pkgs.pkgs.<name>".
    bare = pkg_name[len("pkgs."):] if pkg_name.startswith("pkgs.") else pkg_name
    ref = bare if "." in bare else f"pkgs.{bare}"

    # C1 defense-in-depth: skip if an equivalent reference is already present.
    for line in content[match.end():closing_pos].split('\n'):
        code = line.strip().split('#')[0].strip()
        if code == ref or code == bare:
            return content

    return content[:closing_pos] + f"{indent}{ref}\n" + content[closing_pos:]


def add_package(content: str, pkg_name: str, config_dir: Path, block: str = "environment.systemPackages") -> AddResult:
    """Add a package to a package block using the detected format.

    Only SUPPORTED_FORMATS may be modified. Unsupported formats return
    `unsupported_<format>` with the original content untouched.
    """
    fmt = detect_format(content, block)
    if fmt not in SUPPORTED_FORMATS:
        return AddResult(content=content, status=f"unsupported_{fmt}")

    try:
        if fmt == "with_pkgs":
            new = add_package_with_pkgs(content, pkg_name, block)
        else:
            new = add_package_explicit_pkgs(content, pkg_name, block)
        if new == content:
            return AddResult(content=content, status="no_change")
        return AddResult(content=new, status="success")
    except Exception:
        return AddResult(content=content, status="error")


def remove_package(content: str, pkg_name: str, config_dir: Path,
                 block: str = "environment.systemPackages",
                 source: str = "stable",
                 unstable_var: str = "unstable") -> tuple[str, bool]:
    """Remove a package from a package block. Returns (new_content, found).

    Source-aware: only removes the reference that matches the requested
    source.  Trailing ``#`` comments on a list entry are ignored during
    comparison so ``"git # my fav"`` is still matched by ``"git"``.

    Returns ``(content, False)`` when the package is not present in the
    requested source — the caller (handle_remove) is responsible for
    presenting ambiguity to the user.
    """
    identity = resolve_identity(pkg_name, source=source, unstable_var=unstable_var)
    fmt = detect_format(content, block)
    if fmt not in SUPPORTED_FORMATS:
        return content, False

    if fmt == "with_pkgs":
        match = re.search(rf'{re.escape(block)}\s*=\s*with\s+pkgs\s*;\s*\[', content)
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
        code = stripped.split('#')[0].strip()
        if not code:
            new_lines.append(line)
            continue
        if identity.source == "stable":
            target = identity.name
            if code == target or code == f"pkgs.{target}":
                found = True
                continue
        else:  # unstable
            if code == identity.reference:
                found = True
                continue
        new_lines.append(line)

    new_inner = '\n'.join(new_lines)
    return content[:start] + new_inner + content[end:], found


@dataclass
class RemoveTarget:
    """Result of resolving a user-supplied remove argument.

    source:      "stable" | "unstable" | "ambiguous"
    name:        bare package name (e.g. "htop")
    reference:   the exact Nix token to remove / match (e.g. "htop",
                 "pkgs.htop", "unstable.htop")
    matches:     list of PackageIdentity entries found in the config
    """
    source: str
    name: str
    reference: str
    matches: list


def resolve_remove_target(content: str, pkg_name: str, config_dir: Path,
                           block: str = "environment.systemPackages",
                           unstable_var: str = "unstable") -> RemoveTarget:
    """Resolve a user remove argument to a precise target.

    * Explicit unstable reference ``"unstable.htop"`` (or with a custom
      unstable_var) → targets that exact unstable entry.
    * Bare name ``"htop"`` → checks both sources:
        - both present → "ambiguous" (default = stable), reports both
        - only stable present  → targets stable
        - only unstable present → targets unstable
        - neither present → source = "missing"
    """
    # Explicit unstable reference?
    if pkg_name.startswith(f"{unstable_var}."):
        name = pkg_name[len(unstable_var) + 1:]
        identity = PackageIdentity(name=name, source="unstable",
                                    reference=pkg_name)
        if is_package_exists(content, pkg_name, config_dir, block,
                             source="unstable", unstable_var=unstable_var):
            return RemoveTarget(source="unstable", name=name,
                                reference=pkg_name, matches=[identity])
        return RemoveTarget(source="unstable", name=name,
                            reference=pkg_name, matches=[])

    # Bare name — check both sources.
    stable_exists = is_package_exists(content, name_if_bare := pkg_name,
                                      config_dir, block, source="stable")
    unstable_exists = is_package_exists(content, pkg_name, config_dir, block,
                                        source="unstable", unstable_var=unstable_var)

    if stable_exists and unstable_exists:
        s_id = PackageIdentity(name=pkg_name, source="stable", reference=pkg_name)
        u_id = PackageIdentity(name=pkg_name, source="unstable",
                               reference=f"{unstable_var}.{pkg_name}")
        return RemoveTarget(source="ambiguous", name=pkg_name,
                            reference=pkg_name, matches=[s_id, u_id])

    if stable_exists:
        return RemoveTarget(source="stable", name=pkg_name,
                            reference=pkg_name, matches=[
            PackageIdentity(name=pkg_name, source="stable", reference=pkg_name)])

    if unstable_exists:
        ref = f"{unstable_var}.{pkg_name}"
        return RemoveTarget(source="unstable", name=pkg_name,
                            reference=ref, matches=[
            PackageIdentity(name=pkg_name, source="unstable", reference=ref)])

    return RemoveTarget(source="missing", name=pkg_name, reference=pkg_name, matches=[])


def is_valid_name(pkg_name: str) -> bool:
    """Check if a package name contains only valid characters."""
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', pkg_name))


def is_package_exists(content: str, pkg_name: str, config_dir: Path,
                   block: str = "environment.systemPackages",
                   source: str = "stable",
                   unstable_var: str = "unstable") -> bool:
    """Check if a package already exists in a package block.

    Source-aware: only references matching the requested source are
    considered a match.  For example, requesting ``stable`` will NOT
    match an ``unstable.htop`` entry, and vice-versa.

    ``pkg_name`` may be a bare name (``"htop"``), an unstable reference
    (``"unstable.htop"``), or an explicit stable reference
    (``"pkgs.htop"``); it is normalized via ``resolve_identity``.
    """
    # A source mismatch in the input is a no-match.  Passing
    # "unstable.htop" with source="stable" is contradictory → False.
    if source == "stable" and pkg_name.startswith(f"{unstable_var}."):
        return False
    identity = resolve_identity(pkg_name, source=source, unstable_var=unstable_var)
    fmt = detect_format(content, block)
    if fmt not in SUPPORTED_FORMATS:
        return False

    if fmt == "with_pkgs":
        match = re.search(rf'{re.escape(block)}\s*=\s*with\s+pkgs\s*;\s*\[', content)
    else:
        match = re.search(rf'{re.escape(block)}\s*=\s*\[', content)

    if not match:
        return False

    pos = match.end()
    depth = 1
    while pos < len(content) and depth > 0:
        if content[pos] == '[':
            depth += 1
        elif content[pos] == ']':
            depth -= 1
        pos += 1

    inner = content[match.end():pos - 1]

    # Build the set of references that count as a match for this identity.
    if identity.source == "stable":
        accepted = {identity.name, f"pkgs.{identity.name}"}
    else:
        accepted = {identity.reference}

    for line in inner.split('\n'):
        code = line.strip().split('#')[0].strip()
        if code in accepted:
            return True
    return False


def is_package_name_taken(content: str, pkg_name: str, config_dir: Path,
                          block: str = "environment.systemPackages",
                          unstable_var: str = "unstable") -> bool:
    """Check if a package *name* is already used in a block, in EITHER source.

    Unlike ``is_package_exists`` (which is source-specific), this checks
    whether the bare package name resolves to any reference form — stable
    (``htop``, ``pkgs.htop``) or unstable (``{unstable_var}.htop``).

    Used by ``handle_install`` for the cross-source collision rule:
    when the user requests an *unstable* package whose name is already
    consumed by a *stable* entry (or vice-versa), the name is treated as
    taken and the install is blocked.
    """
    identity = resolve_identity(pkg_name, source="stable", unstable_var=unstable_var)
    fmt = detect_format(content, block)
    if fmt not in SUPPORTED_FORMATS:
        return False

    if fmt == "with_pkgs":
        match = re.search(rf'{re.escape(block)}\s*=\s*with\s+pkgs\s*;\s*\[', content)
    else:
        match = re.search(rf'{re.escape(block)}\s*=\s*\[', content)
    if not match:
        return False

    pos = match.end()
    depth = 1
    while pos < len(content) and depth > 0:
        if content[pos] == '[':
            depth += 1
        elif content[pos] == ']':
            depth -= 1
        pos += 1

    inner = content[match.end():pos - 1]
    # Accept: bare name, pkgs.<name>, or {unstable_var}.<name>
    accepted = {identity.name, f"pkgs.{identity.name}",
                f"{unstable_var}.{identity.name}"}
    for line in inner.split('\n'):
        code = line.strip().split('#')[0].strip()
        if code in accepted:
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


def add_flake_package(content: str, flake_name: str, pkg_attr: str, system_var: str = "pkgs.stdenv.hostPlatform.system", block: str | None = None) -> AddResult:
    """Add a flake package reference to a package block.

    block=None → legacy auto-detect: home.packages first, then the
    systemPackages default. The Home→System fallback applies only when
    the home block is actually MISSING — a home block that exists in an
    unsupported format keeps its unsupported status (no silent fallback).

    block="home.packages" / "environment.systemPackages" → target that
    block explicitly; never falls back elsewhere.

    All format decisions flow through detect_format()/SUPPORTED_FORMATS
    via add_package — there is no separate insertion path here.
    """
    pkg_line = f"inputs.{flake_name}.packages.${{{system_var}}}.{pkg_attr}"

    if block is not None:
        return add_package(content, pkg_line, Path("."), block)

    home_fmt = detect_format(content, "home.packages")
    if home_fmt != "missing":
        # home.packages exists (supported or not) — it keeps the target.
        return add_package(content, pkg_line, Path("."), "home.packages")
    return add_package(content, pkg_line, Path("."))


def _find_brace_end(content: str, open_pos: int) -> int | None:
    """Return the index of the `}` matching the `{` at open_pos, or None.

    Correctly skips over:
      * double-quoted strings (with ``\\`` escaped characters)
      * Nix ``#`` line comments
      * Nix indented strings (``'' ... ''``)
    """
    depth = 1
    pos = open_pos + 1
    n = len(content)
    while pos < n:
        ch = content[pos]
        if ch == "#":
            nl = content.find("\n", pos)
            pos = n if nl == -1 else nl + 1
            continue
        if ch == '"':
            # Double-quoted string with escape handling.
            pos += 1
            while pos < n:
                if content[pos] == "\\":
                    pos += 2
                    continue
                if content[pos] == '"':
                    pos += 1
                    break
                pos += 1
            continue
        if content.startswith("''", pos):
            end = content.find("''", pos + 2)
            if end == -1:
                return None
            pos = end + 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return pos
        pos += 1
    return None


def _find_nixos_modules_list(
    content: str, target_config: str | None = None
) -> tuple[int, int, int] | None:
    """Locate the top-level ``modules = [ ... ]`` list inside a nixosSystem.

    Searches for ``nixosConfigurations.<name>`` (the first one when
    *target_config* is None, or the one matching *target_config*
    otherwise).

    From that configuration, it locates the ``nixosSystem`` invocation and
    its argument attrset. The target ``modules = [ ... ]`` must be at the
    top level of that attrset. Nested lists such as:

        specialArgs = {
            modules = [
                ./fake.nix
            ];
        };

    are deliberately ignored.

    Returns ``(match_start, list_open_pos, list_close_pos)`` where
    ``match_start`` is the start of ``modules =``, ``list_open_pos`` is the
    opening ``[``, and ``list_close_pos`` is the matching closing ``]``.

    Returns ``None`` when the expected structure cannot be located.

    This function is intentionally fail-safe: it never falls back to a
    global ``modules = [`` search.
    """
    cfg_re = re.compile(
        r"nixosConfigurations\s*\.\s*"
        + (
            re.escape(target_config)
            if target_config
            else r"[A-Za-z_][\w-]*"
        )
    )

    cfg_match = cfg_re.search(content)
    if not cfg_match:
        return None

    pos = cfg_match.end()
    n = len(content)

    ns_kw_re = re.compile(r"\bnixosSystem\b")
    next_cfg_re = re.compile(r"nixosConfigurations\s*\.")

    search_region_end = n
    next_cfg = next_cfg_re.search(content, pos)
    if next_cfg:
        search_region_end = next_cfg.start()

    ns_match = ns_kw_re.search(content, pos)
    if not ns_match or ns_match.start() >= search_region_end:
        return None

    ns_end = ns_match.end()

    # The nixosSystem argument attrset must begin after the keyword.
    brace_pos = _skip_ws_and_comments(content, ns_end)

    if brace_pos >= n or content[brace_pos] != "{":
        return None

    block_end = _find_brace_end(content, brace_pos)
    if block_end is None:
        return None

    # Scan only the nixosSystem attrset and track brace depth.
    #
    # depth == 0 means we are directly inside:
    #
    #   nixosSystem {
    #       ...
    #   }
    #
    # Nested attrsets such as specialArgs = { ... } therefore have
    # depth > 0 and their ``modules`` keys are ignored.
    i = brace_pos + 1
    depth = 0

    while i < block_end:
        i = _skip_ws_and_comments(content, i)

        if i >= block_end:
            break

        char = content[i]

        # Skip strings completely so text such as:
        # "modules = ["
        # cannot be mistaken for real Nix syntax.
        if char == '"':
            i += 1
            while i < block_end:
                if content[i] == "\\":
                    i += 2
                    continue
                if content[i] == '"':
                    i += 1
                    break
                i += 1
            continue

        # Skip Nix indented strings.
        if content.startswith("''", i):
            end = content.find("''", i + 2, block_end)
            if end == -1:
                return None
            i = end + 2
            continue

        if char == "{":
            depth += 1
            i += 1
            continue

        if char == "}":
            depth -= 1
            i += 1
            continue

        # Only inspect ``modules = [`` at the top level of the
        # nixosSystem attrset.
        if depth == 0 and content.startswith("modules", i):
            match = re.match(r"modules\s*=\s*\[", content[i:block_end])

            if match:
                list_open = i + match.end() - 1
                list_close = _find_list_end(content, list_open)

                if list_close is None or list_close > block_end:
                    return None

                return (i, list_open, list_close)

        i += 1

    return None


def _find_outermost_close(content: str) -> int | None:
    """Index of the file's last top-level ``}``, skipping strings/comments.

    Used as the insertion anchor when a whole new attribute block must be
    appended. ``str.rfind('}')`` is unsafe here: a ``}`` inside a string or
    a trailing comment would be picked instead of the real closing brace,
    splicing the new block into the middle of that literal.
    """
    depth = 0
    last = None
    pos = 0
    n = len(content)
    while pos < n:
        ch = content[pos]
        if ch == "#":
            nl = content.find("\n", pos)
            pos = n if nl == -1 else nl + 1
            continue
        if ch == '"':
            pos += 1
            while pos < n:
                if content[pos] == "\\":
                    pos += 2
                    continue
                if content[pos] == '"':
                    pos += 1
                    break
                pos += 1
            continue
        if content.startswith("''", pos):
            end = content.find("''", pos + 2)
            if end == -1:
                break
            pos = end + 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last = pos
        pos += 1
    return last


def _insert_list_element(content: str, list_open: int, list_close: int,
                         element: str) -> str:
    """Insert *element* into the list spanning [list_open, list_close].

    Shared by add_flake_module and add_flake_overlay so both obey the same
    formatting contract:

      * the new entry lines up with the list's existing entries;
      * the closing ``]`` keeps its own line and indentation — it must never
        collapse to column 0;
      * a non-empty one-line list keeps its inline shape;
      * an empty list (``[]`` or a blank multi-line list) is expanded.

    Indentation is taken from the statement that owns the list and from the
    first real entry — never from the last line, which may be the closing
    brace of a nested attrset rather than a sibling entry.
    """
    inner = content[list_open + 1:list_close]

    # Non-empty one-line list: append in place, keep it on one line.
    if "\n" not in inner and inner.strip():
        return (content[:list_close].rstrip(" \t")
                + f" {element} " + content[list_close:])

    # Indentation of the first real entry of the list.
    element_indent = None
    for line in inner.split("\n")[1:]:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            element_indent = line[: len(line) - len(line.lstrip())]
            break

    # Indentation of the statement that owns the list.
    line_start = content.rfind("\n", 0, list_open) + 1
    prefix = content[line_start:list_open]
    statement_indent = prefix[: len(prefix) - len(prefix.lstrip())]

    if element_indent is None:
        # Empty list: no entry to copy from, derive it from the statement.
        element_indent = statement_indent + "  "

    # Keep the closing bracket on its own, correctly indented line.
    close_line_start = content.rfind("\n", 0, list_close) + 1
    close_prefix = content[close_line_start:list_close]

    if close_prefix.strip() == "":
        # `]` already sits alone on its line: preserve that indentation
        # instead of letting the new entry line absorb it.
        closing_indent = close_prefix
        head = content[:close_line_start]
    else:
        # `]` shares its line with the last entry — split it off.
        closing_indent = statement_indent
        head = content[:list_close].rstrip(" \t")

    if not head.endswith("\n"):
        head += "\n"

    # Blank line after a multi-line attrset entry, matching surrounding style.
    if head.rstrip("\n").endswith("}") and not head.endswith("\n\n"):
        head += "\n"

    return (head + f"{element_indent}{element}\n"
            + closing_indent + content[list_close:])


def add_flake_module(
    content: str,
    flake_name: str,
    module_name: str,
    target_config: str | None = None,
) -> str:
    """Add a nixosModule reference to the modules list in flake.nix.

    *target_config* (if provided) selects which
    ``nixosConfigurations.<name>`` block to target.  When omitted the first
    ``nixosConfigurations`` declaration is used.  The function only writes
    into a ``modules = [ ... ]`` list that belongs to a ``nixosSystem``
    invocation — it never falls back to a global ``modules = [`` search, so
    unrelated ``modules`` lists in the flake are left untouched.

    Formatting is delegated to _insert_list_element: the new element lines
    up with the existing entries, and the closing ``];`` keeps its
    indentation instead of collapsing to column 0.
    """
    module_line = f"{flake_name}.nixosModules.{module_name}"

    found = _find_nixos_modules_list(content, target_config)
    if found is None:
        # No nixosSystem block found — fail safe, do not mutate.
        return content

    _, list_open, list_close = found

    if module_line in content[list_open + 1:list_close]:
        return content

    return _insert_list_element(content, list_open, list_close, module_line)

def add_flake_overlay(content: str, flake_name: str, overlay_name: str) -> str:
    """Add an overlay reference to nixpkgs.overlays, creating it if needed.

    The reference uses the `inputs.` namespace: the overlay line is written
    into configuration.nix/home.nix, where only `inputs.<name>` is in scope
    (via specialArgs), never the bare flake name.

    Formatting is delegated to _insert_list_element, so an existing list
    keeps its entry indentation and its closing ``];`` line. When no list
    exists, a new block is appended before the file's outermost ``}`` —
    located with a string/comment-aware scan, not ``str.rfind('}')``.
    """
    overlay_line = f"inputs.{flake_name}.overlays.{overlay_name}"

    match = re.search(r'nixpkgs\.overlays\s*=\s*\[', content)
    if match:
        list_open = match.end() - 1
        list_close = _find_list_end(content, list_open)
        if list_close is None:
            return content

        if overlay_line in content[list_open + 1:list_close]:
            return content

        return _insert_list_element(content, list_open, list_close, overlay_line)

    anchor = _find_outermost_close(content)
    if anchor is None:
        return content

    # Indent the new block to match the file's existing top-level attributes.
    line_start = content.rfind("\n", 0, anchor) + 1
    prefix = content[line_start:anchor]
    body_indent = prefix[: len(prefix) - len(prefix.lstrip())] or "  "

    new_block = (
        f"{body_indent}nixpkgs.overlays = [\n"
        f"{body_indent}  {overlay_line}\n"
        f"{body_indent}];\n"
    )
    return content[:anchor] + new_block + content[anchor:]


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
    target_config: str | None = None,
) -> tuple[str, str | None, str]:
    """High-level function to add a flake input and reference.

    The input declaration always goes to flake_content (flake.nix); the
    package reference goes to home_content (the selected target file)
    when provided, else into flake_content. `block` names the package
    block inside the target file; None keeps legacy auto-detection.

    Returns (flake_content, home_content, status). status is the
    writer-level result status of the package-reference operation
    ("success" for non-package types); callers must check it before
    rebuilding.
    """
    status = "success"
    if not is_input_exists(flake_content, flake_name):
        flake_content = add_flake_input(flake_content, flake_name, flake_url, follows)
        flake_content = add_flake_to_outputs(flake_content, flake_name)
    
    if pkg_type == "package":
        if home_content is not None:
            result = add_flake_package(home_content, flake_name, pkg_attr, block=block)
            home_content = result.content
            status = result.status
        else:
            result = add_flake_package(flake_content, flake_name, pkg_attr, block=block)
            flake_content = result.content
            status = result.status
    elif pkg_type == "nixosModule":
        flake_content = add_flake_module(flake_content, flake_name, module_name,
                                         target_config=target_config)
    elif pkg_type == "overlay":
        pass
    elif pkg_type == "homeModule":
        if home_content is not None:
            home_content = add_home_flake_module(home_content, flake_name, module_name)
    
    return flake_content, home_content, status


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
    """Build the final Nix reference for a package based on source and format.

    Produces exactly one of:
      * ``{unstable_var}.{name}``  — unstable source
      * ``pkgs.{name}``            — stable + explicit_pkgs format
      * ``{name}``                 — stable + with_pkgs format

    The input ``name`` is always the *bare* package name (e.g. ``"htop"``).
    A doubled prefix like ``"pkgs.pkgs.htop"`` can never occur here because
    we only prepend when source/unstable_var is involved, and we strip a
    leading ``"pkgs."`` first so re-entry is idempotent.
    """
    # Normalize: never accept or propagate an already-qualified reference as
    # the "name" — that way callers cannot accidentally double-prefix.
    bare = name[len("pkgs."):] if name.startswith("pkgs.") else name
    bare = bare[len(unstable_var) + 1:] if bare.startswith(f"{unstable_var}.") else bare
    if source == "unstable":
        return f"{unstable_var}.{bare}"
    if fmt == "explicit_pkgs":
        return f"pkgs.{bare}"
    return bare
