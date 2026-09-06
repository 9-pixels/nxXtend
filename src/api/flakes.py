import subprocess
import json
import re
import urllib.request
from src.models.package import Package
import platform

SYSTEM = f"{platform.machine()}-linux"


def extract_block(content: str, start: int) -> str | None:
    """Extract content between balanced braces starting at position of opening '{'."""
    depth = 0
    i = start
    while i < len(content):
        if content[i] == '{':
            depth += 1
        elif content[i] == '}':
            depth -= 1
            if depth == 0:
                return content[start + 1:i]
        i += 1
    return None


def flake_fetch_raw(flake_url: str) -> str | None:
    """Fetch flake.nix content from GitHub API — fast, no nix evaluation."""
    if not flake_url.startswith("github:"):
        return None

    repo = flake_url.removeprefix("github:")

    for branch in ["HEAD", "master", "main"]:
        api_url = f"https://raw.githubusercontent.com/{repo}/{branch}/flake.nix"
        try:
            with urllib.request.urlopen(api_url, timeout=10) as response:
                return response.read().decode("utf-8")
        except Exception:
            continue

    return None


def flake_parse_packages(content: str) -> list[str] | None:
    """Parse package names from flake.nix content — returns None if structure is too complex."""
    
    block = _find_block(content, "packages")

    if not block:
        return None

    if re.search(r'\bimport\b\s+\./', block):
        return None

    names = re.findall(r'^\s*([a-zA-Z0-9_-]+)\s*=', block, re.MULTILINE)
    names = [n for n in names if n not in ("default", "inherit", "self")]

    return names if names else None

def flake_parse_outputs(content: str) -> list[FlakeOutput]:
    """Parse all relevant outputs from flake.nix content."""

    output_types = [
        "packages",
        "legacyPackages",
        "nixosModules",
        "nixosModule",
        "overlays",
        "overlay",
        "homeModules",
        "homeManagerModules",
    ]

    outputs = []

    for output_type in output_types:
        if not re.search(rf'\b{output_type}\b', content):
            continue

        block = _find_block(content, output_type)

        if block is None:
            # check for import or callPackage as direct source
            match = re.search(
                rf'\b{output_type}\s*=\s*(?:import|[a-zA-Z.]+callPackage)\s+(\.\/[^\s;{{]+)',
                content
            )
            if match:
                outputs.append(FlakeOutput(type=output_type, source=match.group(1)))
            continue

        # check if block itself points to a file
        source = None
        source_match = re.search(
            r'=\s*(?:import|[a-zA-Z.]+callPackage)\s+(\.\/[^\s;{{]+)',
            block
        )
        if source_match:
            source = source_match.group(1)

        names = re.findall(r'^\s*([a-zA-Z0-9_-]+)\s*=', block, re.MULTILINE)
        names = [n for n in names if n not in ("default", "inherit", "self")]

        outputs.append(FlakeOutput(type=output_type, source=source, names=names))

    return outputs

def flake_group_outputs(outputs: list[FlakeOutput]) -> dict:
    """Group outputs into alternatives (same source) and complements (different sources)."""
    
    # group by source
    source_groups: dict[str, list[FlakeOutput]] = {}
    no_source: list[FlakeOutput] = []

    for output in outputs:
        if output.source:
            source_groups.setdefault(output.source, []).append(output)
        else:
            no_source.append(output)

    alternatives = [group for group in source_groups.values() if len(group) > 1]
    singles = [group[0] for group in source_groups.values() if len(group) == 1]

    complements = singles + no_source

    return {
        "alternatives": alternatives,  # المستخدم يختار واحداً منها
        "complements": complements      # تُضاف كلها معاً
    }

def flake_search(flake_url: str) -> list[Package]:
    """List packages from a flake — tries GitHub API first, falls back to nix eval."""
    raw = flake_fetch_raw(flake_url)
    if raw:
        names = flake_parse_packages(raw)
        if names is not None:
            return [
                Package(
                    name=name,
                    version=None,
                    description=None,
                    source=flake_url,
                    type="package",
                    attribute=name
                )
                for name in names
            ]

    # Slow path: nix eval
    try:
        result = subprocess.run(
            [
                "nix", "eval",
                f"{flake_url}#packages.{SYSTEM}",
                "--apply", "builtins.attrNames",
                "--json",
                "--no-write-lock-file",
                "--no-accept-flake-config"
            ],
            capture_output=True,
            text=True,
            timeout=60
        )
    except subprocess.TimeoutExpired:
        return []

    if result.returncode != 0 or not result.stdout.strip():
        return []

    names = json.loads(result.stdout)

    return [
        Package(
            name=name,
            version=None,
            description=None,
            source=flake_url,
            type="package",
            attribute=name
        )
        for name in names
        if name != "default"
    ]


def flake_get_info(flake_url: str, pkg_attr: str) -> dict:
    """Get full info for a specific package using `nix flake show` — called after user selection."""
    try:
        result = subprocess.run(
            [
                "nix", "flake", "show", "--json",
                "--no-write-lock-file",
                "--no-accept-flake-config",
                flake_url
            ],
            capture_output=True,
            text=True,
            timeout=120
        )
    except subprocess.TimeoutExpired:
        return {}

    if result.returncode != 0 or not result.stdout.strip():
        return {}

    data = json.loads(result.stdout)
    system_pkgs = data.get("packages", {}).get(SYSTEM, {})
    return system_pkgs.get(pkg_attr, {})

def _find_block(content: str, pattern: str) -> str | None:
    """Find and extract a balanced brace block for a given output pattern."""

    # Pattern 1: pattern.system = { ... }
    match = re.search(rf'\b{pattern}\.[a-z0-9_-]+\s*=\s*\{{', content)
    if match:
        return extract_block(content, match.end() - 1)

    # Pattern 2: pattern = { system = { ... }; }
    match = re.search(rf'\b{pattern}\s*=\s*\{{\s*[a-z0-9_-]+\s*=\s*\{{', content)
    if match:
        inner = re.search(r'\{', content[match.start():])
        if inner:
            second = re.search(r'\{', content[match.start() + inner.end():])
            if second:
                pos = match.start() + inner.end() + second.start()
                return extract_block(content, pos)

    # Pattern 3: pattern = forAllSystems/eachSystem/eachDefaultSystem/lib.genAttrs (... { ... })
    match = re.search(
        rf'\b{pattern}\s*=\s*(?:lib\.)?(?:forAllSystems|eachSystem|eachDefaultSystem|genAttrs)\s*[^{{]*\{{',
        content
    )
    if match:
        return extract_block(content, match.end() - 1)

    # Pattern 4: perSystem = { ... }: { pattern = { ... }; }
    match = re.search(r'\bperSystem\s*=', content)
    if match:
        pkg_match = re.search(rf'\b{pattern}\s*=\s*\{{', content[match.start():])
        if pkg_match:
            pos = match.start() + pkg_match.end() - 1
            return extract_block(content, pos)

    return None