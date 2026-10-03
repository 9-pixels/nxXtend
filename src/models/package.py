from dataclasses import dataclass

@dataclass
class Package:
    """Represents a Nix package found during search.

    Two distinct identities are carried deliberately:

      ``name``      upstream derivation pname (``package_pname``). Display and
                    metadata only — it is NOT a valid Nix reference. For the
                    attribute ``nxXtend`` this is ``"nx"``.

      ``attribute`` canonical Nix attribute path (``package_attr_name``), used
                    for every Nix reference, duplicate check and collision
                    check. It already contains any attribute-set prefix, e.g.
                    ``"nxXtend"`` or
                    ``"python314Packages.xstatic-asciinema-player"`` — the
                    bare path, without a leading ``pkgs.``.

    ``name`` and ``attribute`` are frequently equal but are never
    interchangeable: ``pkgs.nx`` and ``pkgs.nxXtend`` are different packages.
    """
    name: str                   # Upstream pname (display/metadata only)
    version: str | None         # Package version (null for flakes)
    description: str | None     # Short package description
    source: str                 # Origin: "stable", "unstable", or flake URL
    type: str | None            # Package type: "package", "nixosModule", "overlay", "homeModule"
    attribute: str              # Canonical Nix attribute path (e.g. "nxXtend")
    install_type: str | None = None  # Where to install: "environment", "home", etc.
