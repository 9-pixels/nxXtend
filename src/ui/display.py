from rich.console import Console
from rich.table import Table
from src.models.package import Package

console = Console()

def show_results(packages: list[Package]) -> list[Package]:
    PAGE_SIZE = 17
    page = 0
    selected = []
    total_pages = (len(packages) + PAGE_SIZE - 1) // PAGE_SIZE
    
    while True:
        console.clear()
        _render_page(packages, page, PAGE_SIZE, selected, total_pages)
        
        choice = input("select (A/D to navigate, Enter to confirm): ").strip()
        
        if choice.lower() == 'a':
            if page > 0:
                page -= 1
        elif choice.lower() == 'd':
            if page < total_pages - 1:
                page += 1
        elif choice == '':
            break
        else:
            try:
                nums = [int(x.strip()) for x in choice.split(',')]
                for num in nums:
                    if 1 <= num <= len(packages):
                        pkg = packages[num - 1]
                        if pkg not in selected:
                            selected.append(pkg)
            except ValueError:
                pass
    
    return selected


def _render_page(packages, page, PAGE_SIZE, selected, total_pages):
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, len(packages))
    
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", width=4)
    table.add_column("Name", width=30)
    table.add_column("Version", width=15)
    table.add_column("Description")
    
    for i, pkg in enumerate(packages[start:end]):
        num = start + i + 1
        table.add_row(
            str(num),
            pkg.name,
            pkg.version or "—",
            pkg.description or "—"
        )
    
    console.print(table)
    console.print(f"── page {page+1}/{total_pages} ── [bold](A)[/bold] prev  [bold](D)[/bold] next")
    console.print(f"selected: {[p.name for p in selected]}")