# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 9-pixels

import argparse
import sys
import subprocess
from pathlib import Path
from rich.console import Console
from src.core.manager import search
from src.flakes.resolver import parse_flake_url, get_metadata
from src.flakes.discovery import discover, classify, get_current_system
from src.flakes.planner import build_plan
from src.flakes.executor import execute
from src.core.writer import (
    add_package, read_config, backup_files, restore_files,
    remove_package, is_package_exists,
    add_flake, remove_flake, remove_flake_reference, is_flake_name_in_content,
    build_package_reference, detect_format
)
from src.core.config import load_config, is_setup_done
from src.ui.first_setup import first_setup
from src.ui.display import (
    show_searching, show_done, show_no_results,
    show_source_select, show_results, show_results_flake,
    show_summary, show_rebuild_start, show_rebuild_done,
    show_unsupported_format
)
from importlib.metadata import version


try:
    VERSION = version("nx")
except Exception:
    VERSION = "dev"

console = Console()


def bootstrap() -> dict:
    if not is_setup_done():
        print("\n  run 'nx setup' first (without sudo)\n")
        sys.exit(1)
    return load_config()

def _filter_supported_outputs(outputs):
    return [
        o for o in outputs
        if classify(o) in {"installable", "configurable", "overlay"}
        and o.type != "homeManagerModules"
    ]

def handle_install(pkg_name: str, config: dict):
    config_file = Path(config["setup"]["configuration_path"])
    config_dir = config_file.parent
    results = {}
    for source, packages in search(pkg_name):
        show_searching(source)
        results[source] = packages
        show_done(source)
    if not results["stable"] and not results["unstable"]:
        show_no_results(pkg_name)
        return
    source = show_source_select(len(results["stable"]), len(results["unstable"]))
    if source == 0:
        return
    packages = results["stable"] if source == 1 else results["unstable"]
    selected = show_results(packages)
    if not selected:
        return
    confirmed = show_summary(selected)
    if not confirmed:
        return
    if not config_file.exists():
        console.print(f"\n  configuration file not found: {config_file}\n")
        return
    try:
        content = read_config(config_file)
        backup_files([config_file])
    except PermissionError:
        console.print("\n  ✗ permission denied — run with sudo\n")
        return
    for pkg in selected:
        fmt = detect_format(content)
        unstable_var = config["setup"].get("unstable_variable", "unstable")
        pkg_ref = build_package_reference(pkg.name, pkg.source, fmt, unstable_var)
        result = add_package(content, pkg_ref, config_dir)
        if result.status != "success":
            show_unsupported_format(result.status)
            restore_files([config_file])
            return
        content = result.content
    config_file.write_text(content)
    show_rebuild_start()
    result = subprocess.run(["nixos-rebuild", "switch", "--flake", str(config_dir)])
    if result.returncode == 0:
        show_rebuild_done(True)
    else:
        try:
            restore_files([config_file])
            show_rebuild_done(False)
        except Exception:
            console.print("\n  ✗ nixos-rebuild failed AND rollback failed — manual check required\n")

def handle_remove(pkg_name: str, config: dict):
    config_file = Path(config["setup"]["configuration_path"])
    config_dir = config_file.parent
    if not config_file.exists():
        console.print(f"\n  configuration file not found: {config_file}\n")
        return
    try:
        content = read_config(config_file)
        if not is_package_exists(content, pkg_name, config_dir):
            console.print(f"\n  package '{pkg_name}' not found in configuration\n")
            return
        confirmed = input(f"\n  remove '{pkg_name}' from configuration? (y/n): ").strip().lower()
        if confirmed != 'y':
            return
        backup_files([config_file])
    except PermissionError:
        console.print("\n  ✗ permission denied — run with sudo\n")
        return
    new_content, found = remove_package(content, pkg_name, config_dir)
    if not found:
        console.print(f"\n  could not remove '{pkg_name}'\n")
        return
    config_file.write_text(new_content)
    show_rebuild_start()
    result = subprocess.run(["nixos-rebuild", "switch", "--flake", str(config_dir)])
    if result.returncode == 0:
        show_rebuild_done(True)
    else:
        try:
            restore_files([config_file])
            show_rebuild_done(False)
        except Exception:
            console.print("\n  ✗ nixos-rebuild failed AND rollback failed — manual check required\n")

def handle_upgrade(config: dict):
    config_file = Path(config["setup"]["configuration_path"])
    config_dir = config_file.parent
    show_rebuild_start()
    result = subprocess.run(["nixos-rebuild", "switch", "--flake", str(config_dir)])
    show_rebuild_done(result.returncode == 0)

def handle_flakes_install(url: str, config: dict):
    # 1 — resolver
    source = parse_flake_url(url)
    source = get_metadata(source)

    # 2 — discovery
    system = get_current_system()
    outputs = discover(source)

    if not outputs:
        show_no_results(url)
        return

    # 3 — filter supported outputs
    supported = _filter_supported_outputs(outputs)

    if not supported:
        console.print(f"\n  no supported outputs found in {url}\n")
        return
    # 4 — user selection
    selected_list = show_results_flake(supported)
    if not selected_list:
        return
    selected = selected_list[0]

    # 5 — planner
    plan = build_plan(source, selected, system)

    # 6 — display plan and confirmation
    confirmed = show_summary([selected])

    # 7 — executor
    show_rebuild_start()
    success = execute(plan, config)
    show_rebuild_done(success)

def handle_flakes_remove(name: str, config: dict):
    flake_file = Path(config["setup"]["flake_path"])
    flake_lock_file = flake_file.parent / "flake.lock"
    config_dir = flake_file.parent
    flake_name = name.split("/")[-1] if "/" in name else name
    
    home_manager_enabled = config["setup"].get("home_manager_enabled", False)
    if home_manager_enabled:
        target_file = Path(config["setup"]["home_manager_path"])
    else:
        target_file = Path(config["setup"]["configuration_path"])
    
    if not flake_file.exists():
        console.print(f"\n  flake file not found: {flake_file}\n")
        return
    
    try:
        flake_content = read_config(flake_file)
    except PermissionError:
        console.print("\n  ✗ permission denied — run with sudo\n")
        return
    
    # Pre-removal validation: check for unknown references in target files
    if target_file.exists():
        target_content_pre = read_config(target_file)
        if is_flake_name_in_content(target_content_pre, flake_name):
            # Check if references are managed by nx (match the pattern add_flake_package creates)
            new_content_check, found_refs = remove_flake_reference(target_content_pre, flake_name)
            if found_refs:
                # Safe to remove — nx created these references
                pass
            else:
                # Flake name found but not in nx-managed pattern — refuse
                console.print(f"\n  ✗ flake '{flake_name}' has unmanaged references in {target_file.name}\n")
                console.print("    remove them manually before removing the flake\n")
                return
    
    # Remove flake from flake.nix
    new_content, found = remove_flake(flake_content, flake_name)
    if not found:
        console.print(f"\n  flake '{flake_name}' not found or was not added by nx\n")
        return
    
    # Clean references in target file
    target_content = read_config(target_file) if target_file.exists() else None
    
    if target_content is not None:
        target_content, _ = remove_flake_reference(target_content, flake_name)
    
    # Build transaction file list
    files = [flake_file]
    if flake_lock_file.exists():
        files.append(flake_lock_file)
    if target_file.exists():
        files.append(target_file)
    
    # Execute transaction
    backup_files(files)
    
    try:
        flake_file.write_text(new_content)
        if target_file.exists() and target_content is not None:
            target_file.write_text(target_content)
    except Exception:
        restore_files(files)
        console.print("\n  ✗ transaction failed during write — changes reverted\n")
        return
    
    show_rebuild_start()
    result = subprocess.run(["nixos-rebuild", "switch", "--flake", str(config_dir)])
    
    if result.returncode == 0:
        show_rebuild_done(True)
    else:
        try:
            restore_files(files)
            show_rebuild_done(False)
        except Exception:
            console.print("\n  ✗ nixos-rebuild failed AND rollback failed — manual check required\n")

def handle_flakes_upgrade(config: dict):
    flake_path = Path(config["setup"]["flake_path"])
    flake_dir = flake_path.parent
    result = subprocess.run(["nix", "flake", "update", str(flake_dir)], cwd=str(flake_dir))
    if result.returncode != 0:
        show_rebuild_done(False)
        return
    show_rebuild_start()
    result = subprocess.run(["nixos-rebuild", "switch", "--flake", str(flake_dir)], cwd=str(flake_dir))
    show_rebuild_done(result.returncode == 0)

def main():
    if len(sys.argv) == 1:
        print(f"\n  nx — NixOS interactive package manager")
        print(f"  version {VERSION}")
        print(f"\n  run 'nx --help' for available commands.\n")
        return

    parser = argparse.ArgumentParser(prog="nx")
    parser.add_argument("--version", "-v", action="store_true")

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("setup")

    install_p = subparsers.add_parser("install")
    install_p.add_argument("name")

    remove_p = subparsers.add_parser("remove")
    remove_p.add_argument("name")

    subparsers.add_parser("upgrade")

    flakes_p = subparsers.add_parser("flakes")
    flakes_p.add_argument("action_or_url", nargs="?", help="URL to install or subcommand (remove, upgrade)")
    flakes_p.add_argument("name", nargs="?", help="Flake name for remove")
    subflakes = flakes_p.add_subparsers(dest="flakes_subcommand")
    subflakes.add_parser("upgrade", aliases=["update"])

    args = parser.parse_args()

    if args.version:
        print(f"\n  nx version {VERSION}\n")
        return

    if args.command == "setup":
        first_setup()
        return

    config = bootstrap()

    if args.command == "install":
        handle_install(args.name, config)
    elif args.command == "remove":
        handle_remove(args.name, config)
    elif args.command == "upgrade":
        handle_upgrade(config)
    elif args.command == "flakes":
        if args.action_or_url and args.action_or_url.startswith("github:"):
            handle_flakes_install(args.action_or_url, config)
        elif args.action_or_url == "remove" and args.name:
            handle_flakes_remove(args.name, config)
        elif args.flakes_subcommand in ("upgrade", "update"):
            handle_flakes_upgrade(config)
        else:
            parser.print_help()

if __name__ == "__main__":
    main()