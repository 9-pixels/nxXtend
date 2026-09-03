import subprocess
import json
from src.models.package import Package
import platform

# Detect current system architecture (e.g. "x86_64-linux")
SYSTEM = f"{platform.machine()}-linux"

def flake_search(flake_url: str) -> list[Package]:
    """Extract packages from a flake using `nix flake show --json`."""
    try:
        result = subprocess.run(
        ["nix", "flake", "show", "--json", "--no-write-lock-file", flake_url],
        capture_output=True,
        text=True,
        timeout=30
        )
    except subprocess.TimeoutExpired:
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []

    data = json.loads(result.stdout)

    # Get packages for the current system architecture
    system_pkgs = data.get("packages", {}).get(SYSTEM, {})

    if SYSTEM == "x86_64-linux":
        # Ignore empty ones (x86_64-linux has many stub entries)
        pkgs = {k: v for k, v in system_pkgs.items() if v}
    else:
        # Show everything even without description (other archs have fewer entries)
        pkgs = system_pkgs
    packages = []
    for pkg_attr, pkg_info in pkgs.items():
        packages.append(Package(
            name=pkg_attr,
            version=None,
            description=pkg_info.get("description") if pkg_info else None,
            source=flake_url,
            type=pkg_info.get("type") if pkg_info else None,
            attribute=pkg_attr
        ))
    return packages