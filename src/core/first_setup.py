import curses
from pathlib import Path

def draw_header(stdscr, page: int, total: int):
    height, width = stdscr.getmaxyx()
    title = "nx setup"
    page_info = f"{page} / {total}"
    
    stdscr.addstr(0, 2, "┌" + "─" * (width - 4) + "┐")
    stdscr.addstr(1, 2, "│")
    stdscr.addstr(1, 4, title)
    stdscr.addstr(1, width - 4 - len(page_info), page_info)
    stdscr.addstr(1, width - 2, "│")
    stdscr.addstr(2, 2, "└" + "─" * (width - 4) + "┘")

def draw_footer(stdscr, hint: str):
    height, width = stdscr.getmaxyx()
    stdscr.addstr(height - 2, 2, "─" * (width - 4))
    stdscr.addstr(height - 1, 2, hint)

def first_setup():
    return curses.wrapper(_setup)

def _setup(stdscr):
    curses.use_default_colors()
    curses.start_color()
    curses.init_pair(1, curses.COLOR_GREEN, -1)  # الأخضر الهادئ
    
    page_welcome(stdscr)
    use_flakes = page_flakes(stdscr)
    
    if use_flakes:
        mode = page_flakes_type(stdscr)
    else:
        mode = 1
    
    config_path = page_config_path(stdscr)
    page_commands(stdscr)
    
    return {"mode": mode, "config_path": config_path}

GREEN = None

def init_colors():
    global GREEN
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    GREEN = curses.color_pair(1) | curses.A_DIM

def draw_highlight(stdscr, row: int, col: int, text: str):
    stdscr.addstr(row, col, text, GREEN)

def draw_text(stdscr, row: int, col: int, text: str):
    stdscr.addstr(row, col, text)

def page_welcome(stdscr):
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    
    draw_header(stdscr, 1, 5)
    
    draw_text(stdscr, 4, 4, "welcome to nx — NixOS interactive package manager")
    draw_text(stdscr, 6, 4, "nx lets you search and install packages from")
    
    col = 4
    draw_highlight(stdscr, 7, col, "stable")
    col += len("stable") + 2
    draw_text(stdscr, 7, col, ",  ")
    col += 3
    draw_highlight(stdscr, 7, col, "unstable")
    col += len("unstable") + 2
    draw_text(stdscr, 7, col, "  and  ")
    col += 7
    draw_highlight(stdscr, 7, col, "flakes")
    
    draw_text(stdscr, 8, 4, "and writes them to your system files automatically.")
    
    draw_footer(stdscr, "press Enter to continue")
    stdscr.refresh()
    
    while True:
        key = stdscr.getch()
        if key in (10, 13):
            break
def page_flakes(stdscr) -> bool:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    
    draw_header(stdscr, 2, 5)
    
    draw_text(stdscr, 4, 4, "do you use flakes?")
    draw_text(stdscr, 6, 4, "flakes are a modern way to manage NixOS configurations.")
    draw_text(stdscr, 7, 4, "they give you reproducible builds and access to more packages.")
    draw_text(stdscr, 8, 4, "if you're not sure, check if you have a")
    draw_highlight(stdscr, 8, 44, "flake.nix")
    draw_text(stdscr, 8, 53, "in your config folder.")
    
    draw_footer(stdscr, "y / n")
    stdscr.refresh()
    
    return input_yes_no(stdscr)

def input_yes_no(stdscr) -> bool:
    while True:
        key = stdscr.getch()
        if key == ord('y') or key == 10 or key == 13:
            return True
        elif key == ord('n'):
            return False

def page_flakes_type(stdscr) -> int:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    
    draw_header(stdscr, 3, 5)
    
    draw_text(stdscr, 4, 4, "how do you manage your flakes?")
    
    draw_text(stdscr, 6, 4, "[1]")
    draw_highlight(stdscr, 6, 8, "configuration.nix + flake.nix")
    draw_text(stdscr, 7, 8, "packages and flakes in their original files")
    
    draw_text(stdscr, 9, 4, "[2]")
    draw_highlight(stdscr, 9, 8, "configuration.nix + flake.nix + home.nix")
    draw_text(stdscr, 10, 8, "user packages go in home.nix")
    
    draw_text(stdscr, 12, 4, "[3]")
    draw_highlight(stdscr, 12, 8, "configuration.nix + flake.nix + nx-flakes.nix")
    draw_text(stdscr, 13, 8, "nx manages flakes in a separate file")
    
    draw_footer(stdscr, "choose (1 / 2 / 3)")
    stdscr.refresh()
    
    return input_choice(stdscr, ["1", "2", "3"])