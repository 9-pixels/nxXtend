import argparse
import sys
import subprocess
from pathlib import Path
from rich.console import Console
from src.core.manager import search, search_flake
from src.core.writer import add_package, read_config, backup_config, remove_package, is_package_exists
from src.ui.display import (
    show_searching, show_done, show_no_results,
    show_source_select, show_results,
    show_summary, show_rebuild_start, show_rebuild_done
)

try:
    from importlib.metadata import version
    VERSION = version("nx")
except Exception:
    VERSION = "dev"

console = Console()
CONFIG = Path("/etc/nixos-test/configuration.nix")

def handle_install(pkg_name: str):
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

    content = read_config(CONFIG)
    backup_config(CONFIG)

    for pkg in selected:
        content = add_package(content, pkg.attribute, CONFIG.parent)

    CONFIG.write_text(content)
    

def handle_remove(pkg_name: str):
    content = read_config(CONFIG)
    
    if not is_package_exists(content, pkg_name, CONFIG.parent):
        console.print(f"\n  package '{pkg_name}' not found in configuration\n")
        return

    backup_config()
    new_content, found = remove_package(content, pkg_name, CONFIG.parent)
    
    if not found:
        console.print(f"\n  could not remove '{pkg_name}'\n")
        return

    CONFIG.write_text(new_content)

    show_rebuild_start()
    result = subprocess.run(["nixos-rebuild", "switch"])
    show_rebuild_done(result.returncode == 0)

def main():
    if len(sys.argv) == 1:
        print(f"\n  nx — NixOS interactive package manager")
        print(f"  version {VERSION}")
        print(f"\n  run 'nx --help' for available commands.\n")
        return

    parser = argparse.ArgumentParser(prog="nx")
    parser.add_argument("--uninstall", action="store_true")

    subparsers = parser.add_subparsers(dest="command")

    install_p = subparsers.add_parser("install")
    install_p.add_argument("name")

    remove_p = subparsers.add_parser("remove")
    remove_p.add_argument("name")

    upgrade_p = subparsers.add_parser("upgrade")
    upgrade_p.add_argument("--flakes", action="store_true")

    flakes_p = subparsers.add_parser("flakes")
    flakes_sub = flakes_p.add_subparsers(dest="flakes_command")
    flakes_p.add_argument("url", nargs="?")
    flakes_sub.add_parser("remove").add_argument("name")

    args = parser.parse_args()

    if args.command == "install":
        handle_install(args.name)
    elif args.command == "remove":
        handle_remove(args.name)
    elif args.command == "upgrade":
        handle_upgrade(args.flakes)
    elif args.command == "flakes":
        if args.flakes_command == "remove":
            handle_flakes(remove=args.name)
        else:
            handle_flakes(url=args.url)
    elif args.uninstall:
        handle_uninstall()

if __name__ == "__main__":
    main()