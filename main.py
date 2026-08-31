import curses
import sys
from src.models.package import Package

PAGE_SIZE = 17

def show_searching(source: str):
    print(f"  searching in {source}...", end="\r", flush=True)

def show_done(source: str):
    print(f"  searching in {source}...     ✓")

def show_no_results(query: str):
    print(f"\n  no results found for \"{query}\"\n")

def show_source_select(stable_count: int, unstable_count: int) -> int:
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
    return curses.wrapper(_show_results_curses, packages)

def _show_results_curses(stdscr, packages: list[Package]) -> list[Package]:
    curses.curs_set(0)  # إخفاء cursor
    stdscr.keypad(True)  # دعم مفاتيح خاصة

    page = 0
    selected = []
    total_pages = (len(packages) + PAGE_SIZE - 1) // PAGE_SIZE
    input_buf = ""  # مخزن الإدخال

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        # رسم الجدول
        # العناوين
        stdscr.addstr(0, 2, f"{'#':<5}{'Name':<32}{'Version':<16}")
        stdscr.addstr(1, 2, "─" * (width - 4))

        # الحزم
        start = page * PAGE_SIZE
        end = min(start + PAGE_SIZE, len(packages))

        for i, pkg in enumerate(packages[start:end]):
            num = start + i + 1
            row = i + 2  # بعد العنوان والخط
            name = (pkg.name[:28] + "..") if len(pkg.name) > 30 else pkg.name
            version = (pkg.version or "—")[:14]
            line = f"{num:<5}{name:<32}{version:<16}"
            stdscr.addstr(row, 2, line)
            if num == 1:
                stdscr.addstr(row, 2 + len(line), "<-- default")

        # سطر التنقل
        nav_row = end - start + 3
        stdscr.addstr(nav_row, 2, f"── page {page+1}/{total_pages} ── (n) next  (p) prev")

        # سطر المحدد
        selected_row = nav_row + 1
        selected_names = ", ".join(p.name for p in selected) if selected else "none"
        stdscr.addstr(selected_row, 2, f"selected: {selected_names}")

        # سطر الإدخال
        input_row = selected_row + 2
        stdscr.addstr(input_row, 2, f"select (y / q / 1,2,3): {input_buf}")
        curses.curs_set(1)  # إظهار cursor عند الإدخال
        stdscr.refresh()

        # قراءة المفتاح
        key = stdscr.getch()

        if key == ord('n'):
            if page < total_pages - 1:
                page += 1
            input_buf = ""
        elif key == ord('p'):
            if page > 0:
                page -= 1
            input_buf = ""
        elif key == ord('y') or key == 10 or key == 13:  # y أو Enter
            if input_buf:
                # معالجة الأرقام المكتوبة
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
                # Enter بدون إدخال = y
                if not selected and packages:
                    selected = [packages[0]]
                break
        elif key == ord('q'):
            selected = []
            break
        elif key == curses.KEY_BACKSPACE or key == 127:
            input_buf = input_buf[:-1]
        elif chr(key).isdigit() or chr(key) == ',':
            input_buf += chr(key)

    return selected

def show_summary(packages: list[Package]) -> bool:
    max_name = max(len(pkg.name) for pkg in packages)
    max_version = max(len(pkg.version or "—") for pkg in packages)
    width = max_name + max_version + 20

    print()
    print(f"  ┌─ summary {'─' * width}┐")
    for pkg in packages:
        line = f"+ {pkg.name:<{max_name}}  {(pkg.version or '—'):<{max_version}}  {pkg.source}"
        print(f"  │  {line:<{width}}│")
    print(f"  └{'─' * (width + 2)}┘")
    print()

    while True:
        choice = input("  confirm? (y/n): ").strip().lower()
        if choice in ('y', ''):
            return True
        elif choice == 'n':
            return False

def show_rebuild_start():
    print("\n  running nixos-rebuild switch...\n")

def show_rebuild_done(success: bool):
    if success:
        print("\n  ✓ done.\n")
    else:
        print("\n  ✗ nixos-rebuild failed — changes reverted.\n")