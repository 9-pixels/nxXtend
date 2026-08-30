from importlib.metadata import version
import argparse
import sys

VERSION = version("nx")

def main():
    if len(sys.argv) == 1:
        print(f"\n  nx — NixOS interactive package manager")
        print(f"  version {VERSION}")
        print(f"\n  run 'nx --help' for available commands.\n")
        return

    parser = argparse.ArgumentParser(prog="nx")
    parser.add_argument("--uninstall", action="store_true")

    subparsers = parser.add_subparsers(dest="command")

    # nx install [pkg]
    install_p = subparsers.add_parser("install")
    install_p.add_argument("name")

    # nx remove [pkg]
    remove_p = subparsers.add_parser("remove")
    remove_p.add_argument("name")

    # nx upgrade
    upgrade_p = subparsers.add_parser("upgrade")
    upgrade_p.add_argument("--flakes", action="store_true")

    # nx flakes
    flakes_p = subparsers.add_parser("flakes")
    flakes_sub = flakes_p.add_subparsers(dest="flakes_command")
    flakes_p.add_argument("url", nargs="?")
    flakes_sub.add_parser("remove").add_argument("name")

    args = parser.parse_args()

if __name__ == "__main__":
    main()