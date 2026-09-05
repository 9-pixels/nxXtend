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
    block = None

    # Pattern 1: packages.x86_64-linux = { ... }
    match = re.search(r'packages\.[a-z0-9_-]+\s*=\s*\{', content)
    if match:
        block = extract_block(content, match.end() - 1)

    # Pattern 2: packages = { x86_64-linux = { ... }; }
    if not block:
        match = re.search(r'packages\s*=\s*\{\s*[a-z0-9_-]+\s*=\s*\{', content)
        if match:
            inner = re.search(r'\{', content[match.start():])
            if inner:
                second = re.search(r'\{', content[match.start() + inner.end():])
                if second:
                    pos = match.start() + inner.end() + second.start()
                    block = extract_block(content, pos)

    # Pattern 3: packages = forAllSystems/eachSystem/eachDefaultSystem/lib.genAttrs (... { ... })
    if not block:
        match = re.search(
            r'packages\s*=\s*(?:lib\.)?(?:forAllSystems|eachSystem|eachDefaultSystem|genAttrs)\s*[^{]*\{',
            content
        )
        if match:
            block = extract_block(content, match.end() - 1)

    # Pattern 4: perSystem = { ... }: { packages = { ... }; }
    if not block:
        match = re.search(r'perSystem\s*=', content)
        if match:
            pkg_match = re.search(r'packages\s*=\s*\{', content[match.start():])
            if pkg_match:
                pos = match.start() + pkg_match.end() - 1
                block = extract_block(content, pos)

    if not block:
        return None

    # Check if packages are imported from a file — too complex
    if re.search(r'\bimport\b\s+\./', block):
        return None

    names = re.findall(r'^\s*([a-zA-Z0-9_-]+)\s*=', block, re.MULTILINE)
    names = [n for n in names if n not in ("default", "inherit", "self")]

    return names if names else None


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