# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 9-pixels

import subprocess
import json
import platform
from flakes.models import FlakeSource, FlakeOutput

def get_current_system() -> str:
    result = subprocess.run(
        ["nix", "eval", "--impure", "--expr", "builtins.currentSystem", "--raw"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()

    # fallback
    machine = platform.machine()
    system = platform.system().lower()
    arch = "x86_64" if machine == "x86_64" else "aarch64"
    return f"{arch}-{system}"

def discover(source: FlakeSource) -> list[FlakeOutput]:
    """Discover available outputs in a flake.
    
    This function calls `nix flake show --json` and parses the result into
    a structured list of FlakeOutput objects. It handles two categories:
    
    - Systemic types (packages, legacyPackages, apps, devShells): these are
      system-specific, so we filter by the current system.
    - Non-systemic types (nixosModules, homeManagerModules, overlays): these
      are system-agnostic.
    
    The `--no-write-lock-file` and `--no-accept-flake-config` flags are
    important: they prevent nix from modifying the local lock file or
    accepting config from the remote flake, which could otherwise change
    system state during discovery.
    """
    result = subprocess.run(
        [
            "nix", "flake", "show", "--json",
            "--no-write-lock-file",
            "--no-accept-flake-config",
            source.url
        ],
        capture_output=True,
        text=True,
        timeout=120
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []

    data = json.loads(result.stdout)
    system = get_current_system()
    outputs = []

    SYSTEMIC_TYPES = {"packages", "legacyPackages", "apps", "devShells"}
    NON_SYSTEMIC_TYPES = {"nixosModules", "homeManagerModules", "overlays"}
    KNOWN_TYPES = SYSTEMIC_TYPES | NON_SYSTEMIC_TYPES


    def _move_default_first(outputs: list[FlakeOutput]) -> list[FlakeOutput]:
        for i, out in enumerate(outputs):
            if out.name == "default":
                return [outputs[i]] + outputs[:i] + outputs[i+1:]
        return outputs

    for output_type, content in data.items():
        if output_type not in KNOWN_TYPES:
            continue

        if output_type in SYSTEMIC_TYPES:
            if not isinstance(content, dict):
                continue
            if system not in content:
                continue
            system_content = content[system]
            if not isinstance(system_content, dict):
                continue
            type_outputs = []
            for name in system_content:
                type_outputs.append(FlakeOutput(
                    name=name,
                    type=output_type,
                    system=system,
                    attribute=f"{output_type}.{system}.{name}"
                ))
            outputs.extend(_move_default_first(type_outputs))

        elif output_type in NON_SYSTEMIC_TYPES:
            if not isinstance(content, dict):
                continue
            type_outputs = []
            for name in content:
                type_outputs.append(FlakeOutput(
                    name=name,
                    type=output_type,
                    system=None,
                    attribute=f"{output_type}.{name}"
                ))
            outputs.extend(_move_default_first(type_outputs))

    return outputs

INSTALLABLE = {"packages", "legacyPackages"}
CONFIGURABLE = {"nixosModules", "homeManagerModules"}
EXECUTABLE = {"apps"}
OVERLAY = {"overlays"}
UNSUPPORTED = {"devShells", "checks"}


def classify(output: FlakeOutput) -> str:
    if output.type in INSTALLABLE:
        return "installable"
    if output.type in CONFIGURABLE:
        return "configurable"
    if output.type in EXECUTABLE:
        return "executable"
    if output.type in OVERLAY:
        return "overlay"
    return "unsupported"