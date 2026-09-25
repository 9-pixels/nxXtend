# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 9-pixels

import curses
import sys
from src.models.package import Package

PAGE_SIZE = 17

def show_searching(source: str):
    """Show a 'searching...' message with carriage return for in-place update."""
    print(f"  searching in {source}...", end="\r", flush=True)

def show_done(source: str):
    """Show a 'done' checkmark after a search completes."""
    print(f"  searching in {source}...     ✓")

def show_no_results(query: str):
    """Display a 'no results' message."""
    print(f"\n  no results found for \"{query}\"\n")

def show_source_select(stable_count: int, unstable_count: int) -> int:
    """Display source selection menu and return user choice (0, 1, or 2)."""
    print()
    print(f"  [1] Stable    ({stable_count})")
    print(f"  [2] Unstable  ({unstable_count})")
    print(f"  [0] Cancel")
    print()

    while True:
        choice = input("  Choose source: ").strip()
        if choice in ("0", "1", "2"):
            return int(choice)
        print("  invalid — 0, 1, or 2 only")

def show_results(packages: list[Package]) -> list[Package]:
    """Open the interactive curses browser and return selected packages."""
    return curses.wrapper(_show_results_curses, packages)

def _show_results_curses(stdscr, packages: list[Package]) -> list[Package]:
    """Interactive curses UI for browsing and selecting packages."""
    curses.use_default_colors()
    curses.curs_set(0)
    stdscr.keypad(True)

    page = 0
    selected = []
    total_pages = (len(packages) + PAGE_SIZE - 1) // PAGE_SIZE
    input_buf = ""

    # Column widths for the table layout
    COL_NUM = 5
    COL_NAME = 32
    COL_VERSION = 16
    TABLE_WIDTH = COL_NUM + COL_NAME + COL_VERSION

    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()

        # Headers
        stdscr.addstr(0, 2, f"{'#':<{COL_NUM}}{'Name':<{COL_NAME}}{'Version':<{COL_VERSION}}")
        stdscr.addstr(1, 2, "─" * TABLE_WIDTH)

        # Packages
        start = page * PAGE_SIZE
        end = min(start + PAGE_SIZE, len(packages))

        for i, pkg in enumerate(packages[start:end]):
            num = start + i + 1
            row = i + 2
            name = (pkg.name[:28] + "..") if len(pkg.name) > 30 else pkg.name
            version = (pkg.version or "—")[:14]
            line = f"{num:<{COL_NUM}}{name:<{COL_NAME}}{version:<{COL_VERSION}}"
            stdscr.addstr(row, 2, line)
            if num == 1:
                stdscr.addstr(row, 2 + len(line), "<-- default")

        # Navigation
        nav_row = end - start + 3
        stdscr.addstr(nav_row, 2, f"── page {page+1}/{total_pages} ── (n) next  (p) prev")

        # Selection indicator
        selected_row = nav_row + 1
        selected_names = ", ".join(p.name for p in selected) if selected else "none"
        stdscr.addstr(selected_row, 2, f"selected: {selected_names}")

        # Input line
        input_row = selected_row + 2
        stdscr.addstr(input_row, 2, f"select (y / q / 1,2,3): {input_buf}")

        curses.curs_set(1)
        stdscr.move(input_row, 2 + len(f"select (y / q / 1,2,3): {input_buf}"))
        stdscr.refresh()

        key = stdscr.getch()

        if key == ord('n'):
            if page < total_pages - 1:
                page += 1
            input_buf = ""
        elif key == ord('p'):
            if page > 0:
                page -= 1
            input_buf = ""
        elif key == ord('y') or key == 10 or key == 13:
            if input_buf:
                try:
                    nums = [int(x.strip()) for x in input_buf.split(',')]
                    for num in nums:
                        if 1 <= num <= len(packages):
                            pkg = packages[num - 1]
                            if pkg not in selected:
                                selected.append(pkg)
                except ValueError:
                    pass
                input_buf = ""
            else:
                if not selected and packages:
                    selected = [packages[0]]
                break
        elif key == ord('q'):
            selected = []
            break
        elif key == curses.KEY_BACKSPACE or key == 127:
            input_buf = input_buf[:-1]
        elif 48 <= key <= 57 or key == ord(','):
            input_buf += chr(key)

    return selected

def show_summary(packages: list) -> bool:
    """Display a summary of selected packages/outputs and ask for confirmation."""
    print()
    print("  summary:")
    print()
    for pkg in packages:
        name = pkg.name
        version = getattr(pkg, 'version', None) or '—'
        source = getattr(pkg, 'source', None) or getattr(pkg, 'type', 'flake')
        print(f"    + {name}  {version}  {source}")
    print()

    while True:
        choice = input("  confirm? (y/n): ").strip().lower()
        if choice in ('y', ''):
            return True
        elif choice == 'n':
            return False
            
def show_rebuild_start():
    """Display 'running nixos-rebuild' message."""
    print("\n  running nixos-rebuild switch...\n")

def show_rebuild_done(success: bool):
    """Display rebuild result — success or failure."""
    if success:
        print("\n  ✓ done.\n")
    else:
        print("\n  ✗ nixos-rebuild failed — changes reverted.\n")


def show_unsupported_format(status: str, block: str | None = None):
    """Display a clear message for unsupported package-list formats."""
    where = f"`{block}`" if block else "the package list"
    reason = {
        "unsupported_empty": (
            f"The package list {where} is empty. nx cannot add packages to an "
            "empty list in Beta. Add at least one package entry in a supported "
            "format, then run the command again."
        ),
        "unsupported_missing": (
            f"No package list {where} was found. nx does not create package "
            "lists automatically in Beta. Create it in a supported format, "
            "then run the command again."
        ),
        "unsupported_external": (
            f"The package list {where} is defined in an external file. nx "
            "cannot modify external package lists. Manage the packages in "
            "that file directly."
        ),
        "unsupported_unknown": (
            f"The package list {where} uses an unsupported format. Supported "
            "formats: `with pkgs; [ ... ]` and explicit `pkgs.<name>` entries. "
            "Adjust the list, then run the command again."
        ),
        "no_change": "No changes were made to the configuration.",
        "error": "The configuration could not be modified.",
    }.get(status, status)
    print(f"\n  ✗ {reason}\n")


def show_install_conflict(selected, conflicts, unstable_var: str = "unstable"):
    """Display a clear, grouped message when pre-validation finds conflicts.

    ``selected`` is the full list of Package objects the user chose.
    ``conflicts`` is the subset of PackageIdentity objects already present.
    """
    # Build identity lookups so we can explain *why* each conflicted.
    by_name = {p.name: p for p in selected}
    lines = ["\n  Cannot install the following packages:"]

    for ident in conflicts:
        pkg = by_name.get(ident.name)
        src_label = "stable" if ident.source == "stable" else "unstable"
        existing = ident.reference
        lines.append(f"\n    {ident.name}")
        lines.append(f"      source: {src_label}")
        lines.append(f"      existing reference: {existing}")

    lines.append("\n  No changes were made.\n")
    print("\n".join(lines))


def show_remove_ambiguous(matches, pkg_name: str, unstable_var: str = "unstable"):
    r"""Display ambiguity when a bare name matches both stable and unstable.

    ``matches`` is a list of PackageIdentity: [stable_id, unstable_id].
    Defaults to stable (removal), and tells the user how to target unstable.
    """
    stable_ref = matches[0].reference if matches[0].source == "stable" else pkg_name
    unstable_ref = matches[1].reference if matches[1].source == "unstable" else f"{unstable_var}.{pkg_name}"
    print()
    print(f"  Multiple packages match '{pkg_name}':")
    print(f"  1. {stable_ref}")
    print(f"  2. {unstable_ref}")
    print()
    print(f"  Default removal target: {stable_ref}")
    print(f"  To remove {unstable_ref} instead, specify the full reference:")
    print(f"  nx remove {unstable_ref}")
    print()


def show_results_flake(packages: list[Package]) -> list[Package]:
    """Open the interactive curses browser for flakes with an 'all' option."""
    return curses.wrapper(_show_results_flake_curses, packages)

def _show_results_flake_curses(stdscr, packages: list[Package]) -> list[Package]:
    curses.use_default_colors()
    curses.curs_set(0)
    stdscr.keypad(True)

    page = 0
    selected = []
    total_pages = (len(packages) + PAGE_SIZE - 1) // PAGE_SIZE
    input_buf = ""

    COL_NUM = 5
    COL_NAME = 32
    COL_VERSION = 16
    TABLE_WIDTH = COL_NUM + COL_NAME + COL_VERSION

    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()

        stdscr.addstr(0, 2, f"{'#':<{COL_NUM}}{'Name':<{COL_NAME}}")
        stdscr.addstr(1, 2, "─" * TABLE_WIDTH)

        start = page * PAGE_SIZE
        end = min(start + PAGE_SIZE, len(packages))

        for i, pkg in enumerate(packages[start:end]):
            num = start + i + 1
            row = i + 2
            if row >= height - 4:
                break
            name = (pkg.name[:28] + "..") if len(pkg.name) > 30 else pkg.name
            line = f"{num:<{COL_NUM}}{name:<{COL_NAME}}"
            if 2 + len(line) < width:
                stdscr.addstr(row, 2, line)

        nav_row = end - start + 3
        stdscr.addstr(nav_row, 2, f"── page {page+1}/{total_pages} ── (n) next  (p) prev")

        selected_row = nav_row + 1
        selected_names = ", ".join(p.name for p in selected) if selected else "none"
        stdscr.addstr(selected_row, 2, f"selected: {selected_names}")

        input_row = selected_row + 2
        stdscr.addstr(input_row, 2, f"select (all / q / 1,2,3): {input_buf}")

        curses.curs_set(1)
        stdscr.move(input_row, 2 + len(f"select (all / q / 1,2,3): {input_buf}"))
        stdscr.refresh()

        key = stdscr.getch()

        if key == ord('n'):
            if page < total_pages - 1:
                page += 1
            input_buf = ""
        elif key == ord('p'):
            if page > 0:
                page -= 1
            input_buf = ""
        elif key == 10 or key == 13:
            if input_buf == "all":
                return packages
            elif input_buf:
                try:
                    nums = [int(x.strip()) for x in input_buf.split(',')]
                    for num in nums:
                        if 1 <= num <= len(packages):
                            pkg = packages[num - 1]
                            if pkg not in selected:
                                selected.append(pkg)
                except ValueError:
                    pass
                input_buf = ""
            else:
                if not selected and packages:
                    selected = [packages[0]]
                break
        elif key == ord('q'):
            selected = []
            break
        elif key == curses.KEY_BACKSPACE or key == 127:
            input_buf = input_buf[:-1]
        elif 32 <= key <= 126:
            input_buf += chr(key)

    return selected