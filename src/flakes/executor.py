# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 9-pixels

import subprocess
from pathlib import Path
from flakes.models import InstallationPlan
from core.target import Target, SYSTEM_BLOCK, HOME_BLOCK
from ui.display import show_error, show_unsupported_format
from core.writer import (
    read_config, backup_files, restore_files,
    add_flake, add_flake_overlay, add_package, build_package_reference,
    detect_format, resolve_package_block,
)


def execute(plan: InstallationPlan, config: dict, target: Target | None = None) -> bool:
    """Execute an installation plan against the system configuration.
    
    This is the top-level entry point for the execution phase. Its job is to
    coordinate backup → modify → rebuild → rollback (if needed). It does not
    perform the modifications itself — that's delegated to writer functions.
    
    The transactional contract:
    1. Back up every file that will be touched
    2. Perform the modifications
    3. Attempt the rebuild
    4. If rebuild fails, restore ALL backed-up files
    
    This means that a failure at any point after backup leaves the system in its
    pre-transaction state. A successful rebuild means the new state persists.
    
    `target` (from -H/--home/-home via the CLI) selects WHERE the package
    reference is written. It overrides the legacy home_manager_enabled
    inference. None preserves the legacy behavior exactly.
    """
    if plan.action in {"unsupported", "configure_home"}:
        return False

    flake_enabled = config["setup"]["flake_enabled"]
    home_manager_enabled = config["setup"].get("home_manager_enabled", False)
    unstable_var = config["setup"].get("unstable_variable", "unstable")

    # Target file selection:
    #   explicit target (from CLI)  → its file, always
    #   no target (legacy/default)  → home_manager_enabled inference, unchanged
    if target is Target.HOME:
        target_file = Path(config["setup"]["home_manager_path"])
        target_block = HOME_BLOCK
    elif target is Target.SYSTEM:
        target_file = Path(config["setup"]["configuration_path"])
        target_block = SYSTEM_BLOCK
    else:
        if home_manager_enabled:
            target_file = Path(config["setup"]["home_manager_path"])
            target_block = HOME_BLOCK
        else:
            target_file = Path(config["setup"]["configuration_path"])
            target_block = SYSTEM_BLOCK

    if flake_enabled:
        flake_file = Path(config["setup"]["flake_path"])
        flake_lock_file = flake_file.parent / "flake.lock"
        config_dir = flake_file.parent
        
        if not flake_file.exists() or not target_file.exists():
            return False
        
        files = [flake_file, target_file]
        if flake_lock_file.exists():
            files.append(flake_lock_file)
        backup_files(files)
        
        flake_content = read_config(flake_file)
        target_content = read_config(target_file)
    else:
        flake_file = None
        flake_lock_file = None
        config_dir = target_file.parent
        
        if not target_file.exists():
            return False
        
        files = [target_file]
        backup_files(files)
        
        flake_content = None
        target_content = read_config(target_file)

    if plan.action == "install":
        # Flake workflow is decided by flake_enabled alone.
        # home_manager_enabled only describes target availability — it must
        # never turn a package operation into a Flake operation.
        if flake_enabled:
            # Flake-based install: add input + reference
            flake_content, target_content, add_status = add_flake(
                flake_content=flake_content or "",
                flake_name=plan.flake_name,
                flake_url=plan.source.url,
                pkg_attr=plan.output.name,
                pkg_type="package",
                home_content=target_content,
                block=target_block,
            )
            if add_status != "success":
                # Unsupported/failed format in the target file: nothing was
                # written — restore backups and stop before any rebuild.
                restore_files(files)
                show_unsupported_format(add_status, target_block)
                return False
        else:
            # Non-flake install: add the package directly to the target file.
            # The block must come from the same decision as the file itself —
            # resolving it here (rather than letting add_package default to the
            # system block) is what makes a home.nix target writable.
            block = resolve_package_block(target_content, target_block)
            fmt = detect_format(target_content, block)
            pkg_ref = build_package_reference(plan.output.name, "stable", fmt, unstable_var)
            result = add_package(target_content, pkg_ref, config_dir, block)
            if result.status not in ("success", "no_change"):
                if result.error:
                    show_error("failed to modify the configuration", result.error)
                else:
                    # An unsupported/missing block must be explained, not
                    # swallowed — the flake path reports it the same way.
                    show_unsupported_format(result.status, block)
                restore_files(files)
                return False
            target_content = result.content
            flake_content = None

    elif plan.action == "configure":
        if flake_enabled:
            target_config = config.get("setup", {}).get("nixos_configuration")
            flake_content, _, _ = add_flake(
                flake_content=flake_content or "",
                flake_name=plan.flake_name,
                flake_url=plan.source.url,
                pkg_attr=plan.output.name,
                pkg_type="nixosModule",
                module_name=plan.output.name,
                target_config=target_config,
            )

    elif plan.action == "overlay":
        if flake_enabled:
            flake_content, _, _ = add_flake(
                flake_content=flake_content or "",
                flake_name=plan.flake_name,
                flake_url=plan.source.url,
                pkg_attr=plan.output.name,
                pkg_type="overlay",
                overlay_name=plan.output.name
            )
        target_content = add_flake_overlay(
            target_content,
            plan.flake_name,
            plan.output.name
        )

    try:
        if flake_file and flake_content is not None:
            flake_file.write_text(flake_content)
        target_file.write_text(target_content)
    except Exception as exc:
        restore_files(files)
        show_error("failed to write configuration files", repr(exc))
        return False

    result = subprocess.run(
        ["nixos-rebuild", "switch", "--flake", str(config_dir)]
    )

    if result.returncode != 0:
        restore_files(files)
        return False

    return True
