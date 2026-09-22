# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 9-pixels

"""Central target selection for nx operations.

Target and source/workflow are separate concepts:

  - Target  (SYSTEM / HOME) — WHERE a package is placed:
      SYSTEM → configuration.nix / environment.systemPackages
      HOME   → home.nix       / home.packages

  - Source/workflow (nixpkgs search vs Flake pipeline) — WHERE a
    package comes from. Controlled by the command and flake_enabled,
    never by the target.

`home_manager_enabled` describes whether integrated Home Manager is
configured on the user's system. It does NOT make an operation a Flake
operation, and it does not change the default target. The default target
is always SYSTEM; only an explicit -H/--home/-home request selects HOME.

This module performs no file I/O and reads no configuration files.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Target(Enum):
    """Where a package operation is applied."""

    SYSTEM = "system"
    HOME = "home"


@dataclass(frozen=True)
class TargetInfo:
    """Resolved target: the file to modify and the package block inside it."""

    target: Target
    file: Path
    block: str


# Block names used by the writer. The writer itself stays unparameterized
# in this step; these constants define the vocabulary for the layers above it.
SYSTEM_BLOCK = "environment.systemPackages"
HOME_BLOCK = "home.packages"


def select_target(config: dict, requested: Target | None = None) -> Target:
    """Decide the operation target.

    Rules:
      - Explicit request (from -H/--home/-home) → Target.HOME.
        Requires home_manager_enabled; the caller is responsible for
        rejecting cleanly when it is not (see require_home_manager).
      - No request → Target.SYSTEM, regardless of home_manager_enabled.
        Enabling integrated Home Manager must not silently redirect
        package installs away from configuration.nix.

    Pure function: no I/O, no config mutation, no flake inspection.
    """
    if requested is Target.HOME:
        return Target.HOME
    return Target.SYSTEM


def resolve_target_info(config: dict, target: Target) -> TargetInfo:
    """Map a target to its file path and package block using config paths.

    Raises KeyError if the config lacks the required path key — callers
    should treat that as an invalid configuration, not a target problem.
    """
    setup = config["setup"]
    if target is Target.HOME:
        return TargetInfo(
            target=Target.HOME,
            file=Path(setup["home_manager_path"]),
            block=HOME_BLOCK,
        )
    return TargetInfo(
        target=Target.SYSTEM,
        file=Path(setup["configuration_path"]),
        block=SYSTEM_BLOCK,
    )


def require_home_manager(config: dict) -> bool:
    """Gate for HOME-target operations.

    Returns True when integrated Home Manager is configured.
    The CLI layer uses this to reject -H requests cleanly before any
    file is touched, with instructions on how to enable it.
    """
    return bool(config["setup"].get("home_manager_enabled", False))
