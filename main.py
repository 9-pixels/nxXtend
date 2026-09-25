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
    remove_package, is_package_exists, is_package_name_taken,
    resolve_identity, resolve_remove_target, PackageIdentity,
    add_flake, remove_flake, remove_flake_reference, is_flake_name_in_content,
    build_package_reference, detect_format, SUPPORTED_FORMATS,
)
from src.core.config import load_config, is_setup_done, CONFIG_FILE
from src.core.target import Target, select_target, resolve_target_info, require_home_manager
from src.ui.first_setup import first_setup
from src.ui.display import (
    show_searching, show_done, show_no_results,
    show_source_select, show_results, show_results_flake,
    show_summary, show_rebuild_start, show_rebuild_done,
    show_unsupported_format, show_install_conflict, show_remove_ambiguous
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

def _reject_home_target_unavailable():
    """Clean rejection when -H is used but integrated Home Manager is off."""
    console.print("\n  ✗ Home Manager is disabled in your nx configuration.\n")
    console.print(f"    To use -H, edit {CONFIG_FILE} and set:\n")
    console.print("      [setup]")
    console.print("      home_manager_enabled = true\n")
    console.print("    Or reconfigure with 'nx setup'.\n")


def _resolve_requested_target(requested: Target | None, config: dict) -> Target | None:
    """Resolve the CLI-requested target, rejecting -H when HM is unavailable.

    Returns None when the request must be aborted (message already printed).
    """
    if requested is None:
        return Target.SYSTEM
    if requested is Target.HOME and not require_home_manager(config):
        _reject_home_target_unavailable()
        return None
    return select_target(config, requested)


def handle_install(pkg_name: str, config: dict, requested: Target | None = None):
    target = _resolve_requested_target(requested, config)
    if target is None:
        return
    info = resolve_target_info(config, target)
    config_file = info.file
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
    except PermissionError:
        console.print("\n  ✗ permission denied — run with sudo\n")
        return

    # Pre-mutation validation: inspect every selected package against the
    # current configuration BEFORE any file is touched.  This enforces the
    # stable-vs-unstable identity contract:
    #   - requesting unstable.htop blocks if unstable.htop exists
    #   - requesting unstable.htop also blocks if a stable htop exists
    #     (the name is already taken in the list)
    #   - requesting stable htop does NOT block on an existing unstable.htop
    unstable_var = config["setup"].get("unstable_variable", "unstable")
    fmt = detect_format(content, info.block)
    if fmt not in SUPPORTED_FORMATS:
        show_unsupported_format(f"unsupported_{fmt}", info.block)
        return

    conflicts = []
    for pkg in selected:
        identity = resolve_identity(pkg.name, pkg.source, unstable_var)
        # Same-source collision: the exact reference already exists.
        if is_package_exists(content, identity.reference, config_dir,
                             info.block, source=pkg.source,
                             unstable_var=unstable_var):
            conflicts.append(identity)
            continue
        # Cross-source collision: when requesting unstable, a same-name
        # stable entry already consumes the name → block (prevent ambiguity).
        if pkg.source == "unstable" and is_package_name_taken(
                content, pkg.name, config_dir, info.block, unstable_var):
            conflicts.append(identity)
            continue

    if conflicts:
        show_install_conflict(selected, conflicts, unstable_var)
        return

    try:
        backup_files([config_file])
    except PermissionError:
        console.print("\n  ✗ permission denied — run with sudo\n")
        return

    for pkg in selected:
        pkg_ref = build_package_reference(pkg.name, pkg.source, fmt, unstable_var)
        result = add_package(content, pkg_ref, config_dir, info.block)
        if result.status != "success":
            show_unsupported_format(result.status, info.block)
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

def handle_remove(pkg_name: str, config: dict, requested: Target | None = None):
    target = _resolve_requested_target(requested, config)
    if target is None:
        return
    info = resolve_target_info(config, target)
    config_file = info.file
    config_dir = config_file.parent
    if not config_file.exists():
        console.print(f"\n  configuration file not found: {config_file}\n")
        return
    try:
        content = read_config(config_file)
    except PermissionError:
        console.print("\n  ✗ permission denied — run with sudo\n")
        return

    unstable_var = config["setup"].get("unstable_variable", "unstable")
    fmt = detect_format(content, info.block)
    if fmt not in SUPPORTED_FORMATS:
        show_unsupported_format(f"unsupported_{fmt}", info.block)
        return

    target_info = resolve_remove_target(content, pkg_name, config_dir,
                                        info.block, unstable_var)

    if target_info.source == "missing":
        console.print(f"\n  package '{pkg_name}' not found in configuration\n")
        return

    if target_info.source == "ambiguous":
        show_remove_ambiguous(target_info.matches, pkg_name, unstable_var)
        # ambiguous defaults to stable (matches[0])
        confirmed = input(f"\n  remove default '{target_info.name}' from configuration? (y/n): ").strip().lower()
        if confirmed != 'y':
            return

    confirmed = input(f"\n  remove '{target_info.reference}' from configuration? (y/n): ").strip().lower()
    if confirmed != 'y':
        return

    try:
        backup_files([config_file])
    except PermissionError:
        console.print("\n  ✗ permission denied — run with sudo\n")
        return
    new_content, found = remove_package(content, pkg_name, config_dir,
                                        info.block,
                                        source=target_info.source if target_info.source != "ambiguous" else "stable",
                                        unstable_var=unstable_var)
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

def _check_flakes_enabled(config: dict) -> bool:
    """Reject flake operations when flake_enabled is false.

    This guard runs before resolver/discovery/planner/executor so that
    nothing touches flake.nix or any other file when the user's setup
    does not use Flakes.
    """
    if not config["setup"].get("flake_enabled", False):
        console.print("\n  ✗ Flake support is disabled in your nx configuration.\n")
        console.print(f"    To enable it, edit {CONFIG_FILE} and set:\n")
        console.print("      [setup]")
        console.print("      flake_enabled = true\n")
        console.print("    Or reconfigure with 'nx setup'.\n")
        return False
    return True


def _check_home_manager_enabled(config: dict) -> bool:
    """Reject Home Manager dependent operations when home_manager_enabled is false."""
    if not config["setup"].get("home_manager_enabled", False):
        console.print("\n  ✗ Home Manager is disabled in your nx configuration.\n")
        console.print(f"    To enable it, edit {CONFIG_FILE} and set:\n")
        console.print("      [setup]")
        console.print("      home_manager_enabled = true\n")
        console.print("    Or reconfigure with 'nx setup'.\n")
        return False
    return True


def handle_flakes_install(url: str, config: dict, requested: Target | None = None):
    if not _check_flakes_enabled(config):
        return

    # Target is resolved once here and flows to the executor.
    # It does NOT change how the flake is resolved, discovered, or planned.
    if requested is Target.HOME and not require_home_manager(config):
        _reject_home_target_unavailable()
        return
    target = select_target(config, requested)
    info = resolve_target_info(config, target)

    # Target-state pre-check: reject a missing target file and unsupported
    # package-list formats before any resolver/discovery work and before
    # any rebuild. All three target states (file missing, block missing,
    # block unsupported) are rejected at this same stage.
    if not info.file.exists():
        console.print(f"\n  configuration file not found: {info.file}\n")
        return
    target_fmt = detect_format(read_config(info.file), info.block)
    if target_fmt not in SUPPORTED_FORMATS:
        show_unsupported_format(f"unsupported_{target_fmt}", info.block)
        return

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

    # 7 — executor (target flows through: input → flake.nix, reference → target file)
    show_rebuild_start()
    success = execute(plan, config, target=target)
    show_rebuild_done(success)

def handle_flakes_remove(name: str, config: dict, requested: Target | None = None):
    if not _check_flakes_enabled(config):
        return

    # Target selection follows the same model as flakes install:
    # default → SYSTEM, explicit -H/--home/-home → HOME.
    # home_manager_enabled only gates HOME availability, never the default.
    if requested is Target.HOME and not require_home_manager(config):
        _reject_home_target_unavailable()
        return
    target = select_target(config, requested)
    target_info = resolve_target_info(config, target)

    flake_file = Path(config["setup"]["flake_path"])
    flake_lock_file = flake_file.parent / "flake.lock"
    config_dir = flake_file.parent
    flake_name = name.split("/")[-1] if "/" in name else name

    target_file = target_info.file

    if not flake_file.exists():
        console.print(f"\n  flake file not found: {flake_file}\n")
        return

    try:
        flake_content = read_config(flake_file)
    except PermissionError:
        console.print("\n  ✗ permission denied — run with sudo\n")
        return

    # Pre-removal validation on the SELECTED target:
    # the flake name may be present but not in an nx-managed pattern —
    # refuse instead of leaving unmanaged references behind.
    if target_file.exists():
        target_content_pre = read_config(target_file)
        if is_flake_name_in_content(target_content_pre, flake_name):
            _, found_refs = remove_flake_reference(target_content_pre, flake_name)
            if not found_refs:
                console.print(f"\n  ✗ flake '{flake_name}' has unmanaged references in {target_file.name}\n")
                console.print("    remove them manually before removing the flake\n")
                return

    # Safety: the flake may still be referenced by the OTHER supported
    # target. Removing the input now would leave a dangling reference
    # there. Keep the input in that case; only the selected target's
    # references are removed.
    other_info = resolve_target_info(config, Target.SYSTEM if target is Target.HOME else Target.HOME)
    keep_input = False
    if other_info.file != target_file and other_info.file.exists():
        other_content = read_config(other_info.file)
        if is_flake_name_in_content(other_content, flake_name):
            keep_input = True

    # Remove flake from flake.nix (skipped when the other target still
    # references it)
    if keep_input:
        new_content, found = flake_content, True
    else:
        new_content, found = remove_flake(flake_content, flake_name)
        if not found:
            console.print(f"\n  flake '{flake_name}' not found or was not added by nx\n")
            return

    # Clean references in the selected target file
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
        if keep_input:
            pass  # input kept — flake.nix content unchanged
        else:
            flake_file.write_text(new_content)
        if target_file.exists() and target_content is not None:
            target_file.write_text(target_content)
    except Exception:
        restore_files(files)
        console.print("\n  ✗ transaction failed during write — changes reverted\n")
        return

    if keep_input:
        console.print(f"\n  kept input '{flake_name}' — still referenced by {other_info.file.name}\n")

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
    if not _check_flakes_enabled(config):
        return

    flake_path = Path(config["setup"]["flake_path"])
    flake_dir = flake_path.parent
    result = subprocess.run(["nix", "flake", "update", str(flake_dir)], cwd=str(flake_dir))
    if result.returncode != 0:
        show_rebuild_done(False)
        return
    show_rebuild_start()
    result = subprocess.run(["nixos-rebuild", "switch", "--flake", str(flake_dir)], cwd=str(flake_dir))
    show_rebuild_done(result.returncode == 0)

SUBCOMMANDS = {"setup", "install", "remove", "upgrade", "flakes"}
SHORT_OPS = {"-i": "install", "-r": "remove", "-u": "upgrade"}
HOME_FLAGS = {"-H", "--home", "-home"}


def _usage_error(message: str):
    """Exit with a CLI usage error (argparse-style exit code 2)."""
    print(f"\n  nx: error: {message}\n", file=sys.stderr)
    sys.exit(2)


def _reject_home_target_unsupported(command: str):
    """Clean rejection when -H is supplied to a command with no Home target.

    'upgrade' and 'flakes upgrade' rebuild the whole system — configuration.nix
    and home.nix are applied together — so a Home-only variant does not exist.
    """
    console.print(f"\n  ✗ '{command}' does not support a Home target (-H).\n")
    console.print("    A rebuild applies configuration.nix and home.nix together.\n")
    sys.exit(1)


def _normalize_short_args(argv: list[str]) -> list[str]:
    """Translate composable short flags into canonical long-form arguments.

    Short forms (-i/-r/-u/-f) are composed before argparse sees them, so the
    existing subcommand parser and handlers are reused unchanged:

        nx -i firefox            → nx install firefox
        nx -f github:x/y         → nx flakes github:x/y        (install default)
        nx -f -i github:x/y      → nx flakes github:x/y        (explicit install)
        nx -f -r github:x/y      → nx flakes remove github:x/y
        nx -f -u                 → nx flakes upgrade
        nx -H -f -r github:x/y   → nx flakes remove -H github:x/y

    -H/--home/-home may appear anywhere among the short flags. Arguments are
    passed through untouched when no short operation flag is present, so all
    long-form behavior is preserved exactly.
    """
    args = argv[1:]
    if not any(a in SHORT_OPS or a == "-f" for a in args):
        return argv

    op_flags: list[str] = []
    flakes = False
    home = False
    rest: list[str] = []

    for a in args:
        if a in SHORT_OPS:
            op_flags.append(a)
        elif a == "-f":
            flakes = True
        elif a in HOME_FLAGS:
            home = True
        else:
            rest.append(a)

    if len(op_flags) > 1:
        _usage_error(f"conflicting operations: {' and '.join(op_flags)}")

    if rest and rest[0] in SUBCOMMANDS:
        _usage_error(f"cannot combine short flags with the '{rest[0]}' command")

    op = SHORT_OPS[op_flags[0]] if op_flags else None

    new_argv = [argv[0]]
    if flakes:
        new_argv.append("flakes")
        if op == "remove":
            new_argv.append("remove")
        elif op == "upgrade":
            new_argv.append("upgrade")
        # op == "install" (or no op) → flake install is the default action
        if home:
            new_argv.append("-H")
    elif op is not None:
        new_argv.append(op)
        if home:
            new_argv.append("-H")
    new_argv.extend(rest)
    return new_argv


def main():
    argv = _normalize_short_args(sys.argv)
    if len(argv) == 1:
        print(f"\n  nx — NixOS interactive package manager")
        print(f"  version {VERSION}")
        print(f"\n  run 'nx --help' for available commands.\n")
        return

    parser = argparse.ArgumentParser(prog="nx")
    parser.add_argument("--version", "-v", action="store_true")

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("setup")

    # -H / --home / -home all select the HOME target (home.nix / home.packages).
    # Default (no flag) is always the SYSTEM target.
    def add_home_flag(subparser):
        subparser.add_argument(
            "-H", "--home", "-home",
            action="store_const",
            const=Target.HOME,
            dest="home_target",
            help="target home.nix (home.packages) instead of configuration.nix",
        )

    install_p = subparsers.add_parser("install")
    install_p.add_argument("name")
    add_home_flag(install_p)

    remove_p = subparsers.add_parser("remove")
    remove_p.add_argument("name")
    add_home_flag(remove_p)

    upgrade_p = subparsers.add_parser("upgrade")
    add_home_flag(upgrade_p)

    flakes_p = subparsers.add_parser("flakes")
    flakes_p.add_argument("action_or_url", nargs="?", help="URL to install or subcommand (remove, upgrade, update)")
    flakes_p.add_argument("name", nargs="?", help="Flake name for remove")
    add_home_flag(flakes_p)

    args = parser.parse_args(argv[1:])

    if args.version:
        print(f"\n  nx version {VERSION}\n")
        return

    if args.command == "setup":
        first_setup()
        return

    config = bootstrap()
    home_target = getattr(args, "home_target", None)

    if args.command == "install":
        handle_install(args.name, config, requested=home_target)
    elif args.command == "remove":
        handle_remove(args.name, config, requested=home_target)
    elif args.command == "upgrade":
        # A rebuild applies configuration.nix and home.nix together — there is
        # no Home-only upgrade. Reject before anything runs.
        if home_target is Target.HOME:
            _reject_home_target_unsupported("nx upgrade")
        handle_upgrade(config)
    elif args.command == "flakes":
        if args.action_or_url and args.action_or_url.startswith("github:"):
            handle_flakes_install(args.action_or_url, config, requested=home_target)
        elif args.action_or_url == "remove" and args.name:
            handle_flakes_remove(args.name, config, requested=home_target)
        elif args.action_or_url in ("upgrade", "update"):
            # Flake update/rebuild is target-independent — reject -H explicitly.
            if home_target is Target.HOME:
                _reject_home_target_unsupported(f"nx flakes {args.action_or_url}")
            handle_flakes_upgrade(config)
        elif args.action_or_url == "install" and args.name:
            # Explicit 'flakes install' spelling — same workflow as the URL form.
            handle_flakes_install(args.name, config, requested=home_target)
        else:
            parser.print_help()

if __name__ == "__main__":
    main()