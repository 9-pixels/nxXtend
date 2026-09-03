from dataclasses import dataclass

@dataclass
class Package:
    """Represents a Nix package found during search."""
    name: str                   # Human-readable name (e.g. "steam")
    version: str | None         # Package version (null for flakes)
    description: str | None     # Short package description
    source: str                 # Origin: "stable", "unstable", or flake URL
    type: str | None            # Package type: "package", "nixosModule", "overlay", "homeModule"
    attribute: str | None       # Full Nix attribute path (e.g. "pkgs.steam")
    install_type: str | None = None  # Where to install: "environment", "home", etc.