import readchar
import os
from rich.table import Table
from rich.console import Console
from rich import box


console = Console()

def show_searching(source: str):
    console.print(f"  searching in {source}...", end="\r", flush=True)

def show_done(source: str):
    console.print(f"  searching in {source}...     ✓")

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

def show_results(packages: list[Package]) -> list[Package]:
    PAGE_SIZE = 17
    page = 0
    selected = []
    total_pages = (len(packages) + PAGE_SIZE - 1) // PAGE_SIZE

    while True:
        console.clear()
        _render_page(packages, page, PAGE_SIZE, selected, total_pages)

        key = readchar.readkey()

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
        elif key.isdigit():
            rest = input(key)
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