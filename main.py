import argparse
import sys
import subprocess
from pathlib import Path
from rich.console import Console
from src.core.manager import search, flake_search, flake_get_info
from src.core.writer import (
    add_package, read_config, backup_config,
    remove_package, is_package_exists,
    add_flake, remove_flake
)
from src.core.config import load_config, is_setup_done
from src.ui.first_setup import first_setup
from src.ui.display import (
    show_searching, show_done, show_no_results,
    show_source_select, show_results, show_results_flake,
    show_summary, show_rebuild_start, show_rebuild_done
)

try:
    from importlib.metadata import version
    VERSION = version("nx")
except Exception:
    VERSION = "dev"

console = Console()

def bootstrap() -> dict:
    if not is_setup_done():
        print("\n  run 'nx setup' first (without sudo)\n")
        sys.exit(1)
    return load_config()

def handle_install(pkg_name: str, config: dict):
    config_path = Path(config["setup"]["config_path"])
    config_file = config_path / "configuration.nix"
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
    content = read_config(config_file)
    backup_config(config_file)
    for pkg in selected:
        content = add_package(content, pkg.attribute, config_path)
    config_file.write_text(content)
    show_rebuild_start()
    result = subprocess.run(["nixos-rebuild", "switch", "--flake", str(config_path)])
    show_rebuild_done(result.returncode == 0)

def handle_remove(pkg_name: str, config: dict):
    config_path = Path(config["setup"]["config_path"])
    config_file = config_path / "configuration.nix"
    content = read_config(config_file)
    if not is_package_exists(content, pkg_name, config_path):
        console.print(f"\n  package '{pkg_name}' not found in configuration\n")
        return
    confirmed = input(f"\n  remove '{pkg_name}' from configuration? (y/n): ").strip().lower()
    if confirmed != 'y':
        return
    backup_config(config_file)
    new_content, found = remove_package(content, pkg_name, config_path)
    if not found:
        console.print(f"\n  could not remove '{pkg_name}'\n")
        return
    config_file.write_text(new_content)
    show_rebuild_start()
    result = subprocess.run(["nixos-rebuild", "switch", "--flake", str(config_path)])
    show_rebuild_done(result.returncode == 0)

def handle_upgrade(config: dict):
    config_path = Path(config["setup"]["config_path"])
    show_rebuild_start()
    result = subprocess.run(["nixos-rebuild", "switch", "--flake", str(config_path)])
    show_rebuild_done(result.returncode == 0)

def handle_flakes_install(url: str, config: dict):
    config_path = Path(config["setup"]["config_path"])
    flake_file = config_path / "flake.nix"

    console.print(f"\n  loading {url}...", end="\r")
    packages = flake_search(url)

    if not packages:
        show_no_results(url)
        return

    selected = show_results_flake(packages)

    if not selected:
        return

    console.print(f"\n  fetching package details...", end="\r")
    for pkg in selected:
        info = flake_get_info(url, pkg.attribute)
        pkg.description = info.get("description")
        pkg.type = info.get("type") or "package"

    confirmed = show_summary(selected)

    if not confirmed:
        return

    flake_content = read_config(flake_file)
    backup_config(flake_file)

    flake_name = url.split("/")[-1]

    for pkg in selected:
        flake_content, _ = add_flake(
            flake_content=flake_content,
            flake_name=flake_name,
            flake_url=url,
            pkg_attr=pkg.attribute,
            pkg_type=pkg.type
        )

    flake_file.write_text(flake_content)

    show_rebuild_start()
    result = subprocess.run(["nixos-rebuild", "switch", "--flake", str(config_path)])
    show_rebuild_done(result.returncode == 0)

def handle_flakes_remove(name: str, config: dict):
    config_path = Path(config["setup"]["config_path"])
    flake_file = config_path / "flake.nix"
    flake_name = name.split("/")[-1] if "/" in name else name
    flake_content = read_config(flake_file)
    backup_config(flake_file)
    new_content, found = remove_flake(flake_content, flake_name)
    if not found:
        console.print(f"\n  flake '{flake_name}' not found or was not added by nx\n")
        return
    flake_file.write_text(new_content)
    show_rebuild_start()
    result = subprocess.run(["nixos-rebuild", "switch", "--flake", str(config_path)])
    show_rebuild_done(result.returncode == 0)

def handle_flakes_upgrade(config: dict):
    config_path = Path(config["setup"]["config_path"])
    result = subprocess.run(["nix", "flake", "update", str(config_path)])
    if result.returncode != 0:
        show_rebuild_done(False)
        return
    show_rebuild_start()
    result = subprocess.run(["nixos-rebuild", "switch", "--flake", str(config_path)])
    show_rebuild_done(result.returncode == 0)

def main():
    if len(sys.argv) == 1:
        print(f"\n  nx — NixOS interactive package manager")
        print(f"  version {VERSION}")
        print(f"\n  run 'nx --help' for available commands.\n")
        return

    parser = argparse.ArgumentParser(prog="nx")
    parser.add_argument("--uninstall", "-u", action="store_true")
    parser.add_argument("--version", "-v", action="store_true")

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("setup")

    install_p = subparsers.add_parser("install")
    install_p.add_argument("name")

    remove_p = subparsers.add_parser("remove")
    remove_p.add_argument("name")

    subparsers.add_parser("upgrade")

    flakes_p = subparsers.add_parser("flakes")
    flakes_sub = flakes_p.add_subparsers(dest="flakes_command")
    flakes_sub.add_parser("upgrade")
    flakes_remove_p = flakes_sub.add_parser("remove")
    flakes_remove_p.add_argument("name")
    flakes_install_p = flakes_sub.add_parser("install")
    flakes_install_p.add_argument("url")

    args = parser.parse_args()

    if args.version:
        print(f"\n  nx version {VERSION}\n")
        return

    if args.command == "setup":
        first_setup()
        return

    if args.uninstall:
        handle_uninstall()
        return

    config = bootstrap()

    if args.command == "install":
        handle_install(args.name, config)
    elif args.command == "remove":
        handle_remove(args.name, config)
    elif args.command == "upgrade":
        handle_upgrade(config)
    elif args.command == "flakes":
        if args.flakes_command == "upgrade":
            handle_flakes_upgrade(config)
        elif args.flakes_command == "remove":
            if not args.name:
                console.print("\n  usage: nx flakes remove <name>\n")
                return
            handle_flakes_remove(args.name, config)
        elif args.flakes_command == "install":
            handle_flakes_install(args.url, config)
        else:
            parser.print_help()

if __name__ == "__main__":
    main()