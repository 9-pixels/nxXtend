import readchar
import os
from rich.table import Table
from rich.console import Console
from src.models.package import Package
import termios
import tty
import sys

def _get_terminal_settings():
    return termios.tcgetattr(sys.stdin.fileno())

def _set_raw():
    tty.setraw(sys.stdin.fileno())

def _restore(settings):
    termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, settings)

console = Console()

def show_searching(source: str):
    console.print(f"  searching in {source}...", end="\r")

def show_done(source: str):
    console.print(f"  searching in {source}...     ✓")

def show_no_results(query: str):
    console.print(f"\n  no results found for \"{query}\"\n")

def show_source_select(stable_count: int, unstable_count: int) -> int:
    console.print()
    console.print(f"  [1] Stable    ({stable_count})")
    console.print(f"  [2] Unstable  ({unstable_count})")
    console.print(f"  [0] Cancel")
    console.print()
    
    while True:
        choice = input("  Choose source: ").strip()
        if choice in ("0", "1", "2"):
            return int(choice)
        console.print("  [red]invalid — 0, 1, or 2 only[/red]")
        
def _render_page(packages, page, PAGE_SIZE, selected, total_pages):
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, len(packages))

    table = Table(box=None, show_header=True, header_style="bold")
    table.add_column("#", width=4)
    table.add_column("Name", width=30)
    table.add_column("Version", width=15)

    for i, pkg in enumerate(packages[start:end]):
        num = start + i + 1
        suffix = "  <- default" if num == 1 else ""
        table.add_row(
            str(num),
            pkg.name + suffix,
            pkg.version or "—"
        )

    console.print(table)
    console.print(f"  ── page {page+1}/{total_pages} ── (n) next  (p) prev")
    console.print(f"\n  select (y / n / 1,2,3): ", end="")

def show_results(packages: list[Package]) -> list[Package]:
    PAGE_SIZE = 17
    page = 0
    selected = []
    total_pages = (len(packages) + PAGE_SIZE - 1) // PAGE_SIZE

    while True:
        console.clear()
        _render_page(packages, page, PAGE_SIZE, selected, total_pages)

        settings = _get_terminal_settings()
        _set_raw()
        key = sys.stdin.read(1)
        _restore(settings)

        if key == 'n':
            if page < total_pages - 1:
                page += 1
        elif key == 'p':
            if page > 0:
                page -= 1
        elif key == 'y':
            if packages:
                selected = [packages[0]]
            break
        elif key == 'q':
            break
        elif key in ('\r', '\n'):
            if selected:
                break
        elif key.isdigit():
            _restore(settings)
            sys.stdout.write(key)
            sys.stdout.flush()
            rest = input()
            raw = key + rest
            try:
                nums = [int(x.strip()) for x in raw.split(',')]
                for num in nums:
                    if 1 <= num <= len(packages):
                        pkg = packages[num - 1]
                        if pkg not in selected:
                            selected.append(pkg)
            except ValueError:
                pass

    return selected

def show_summary(packages: list[Package]) -> bool:
    console.print()
    console.print("  ┌─ summary " + "─" * 35 + "┐")
    for pkg in packages:
        line = f"  + {pkg.name:<20} {pkg.version or '—':<12} {pkg.source}"
        console.print(f"  │  {line:<43}│")
    console.print("  └" + "─" * 45 + "┘")
    console.print()

    while True:
        choice = input("  confirm? (y/n): ").strip().lower()
        if choice == 'y':
            return True
        elif choice == 'n':
            return False

def show_rebuild_start():
    console.print("\n  running nixos-rebuild switch...\n")

def show_rebuild_done(success: bool):
    if success:
        console.print("\n  ✓ done.\n")
    else:
        console.print("\n  ✗ nixos-rebuild failed — changes reverted.\n")