# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 9-pixels

import curses
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from src.core.config import CONFIG_FILE, save_config


# ─── Palette ──────────────────────────────────────────────────────────────────

NORMAL_PAIR = 1
DIM_PAIR = 2
ACCENT_PAIR = 3
INPUT_PAIR = 4
SUCCESS_PAIR = 5
ERROR_PAIR = 6
LABEL_PAIR = 7


def init_colors():
    curses.start_color()
    curses.use_default_colors()

    curses.init_pair(NORMAL_PAIR, curses.COLOR_WHITE, -1)
    curses.init_pair(DIM_PAIR, curses.COLOR_WHITE, -1)
    curses.init_pair(ACCENT_PAIR, curses.COLOR_CYAN, -1)

    # Transparent input field.
    curses.init_pair(INPUT_PAIR, curses.COLOR_WHITE, -1)

    curses.init_pair(SUCCESS_PAIR, curses.COLOR_GREEN, -1)
    curses.init_pair(ERROR_PAIR, curses.COLOR_RED, -1)
    curses.init_pair(LABEL_PAIR, curses.COLOR_YELLOW, -1)


def normal():
    return curses.color_pair(NORMAL_PAIR)


def dim():
    return curses.color_pair(DIM_PAIR) | curses.A_DIM


def accent():
    return curses.color_pair(ACCENT_PAIR) | curses.A_BOLD


def input_attr():
    return curses.color_pair(INPUT_PAIR)


def success():
    return curses.color_pair(SUCCESS_PAIR) | curses.A_BOLD


def error():
    return curses.color_pair(ERROR_PAIR)


def label():
    return curses.color_pair(LABEL_PAIR) | curses.A_BOLD


# ─── Layout ───────────────────────────────────────────────────────────────────

PANEL_W = 62
PANEL_H = 20
INNER_PAD = 2


# ─── State ────────────────────────────────────────────────────────────────────

@dataclass
class Config:
    configuration_path: str = "/etc/nixos/configuration.nix"
    flake_enabled: bool = False
    flake_path: str = "/etc/nixos/flake.nix"
    home_manager_enabled: bool = False
    home_manager_path: str = "/etc/nixos/home.nix"
    unstable_variable: str = "unstable"


class Back(Exception):
    """Return to the previous setup page."""


class Quit(Exception):
    """Cancel the setup wizard."""


# ─── Validation ───────────────────────────────────────────────────────────────

def validate_nix_path(value: str) -> Optional[str]:
    value = value.strip()

    if not value:
        return "Path cannot be empty."

    if not value.startswith("/"):
        return "Must be an absolute path."

    if not value.endswith(".nix"):
        return "Must point to a .nix file."

    return None


def validate_var_name(value: str) -> Optional[str]:
    value = value.strip()

    if not value:
        return "Variable name cannot be empty."

    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", value):
        return "Must be a valid Nix identifier."

    return None


# ─── Panel ────────────────────────────────────────────────────────────────────

class Panel:
    """
    Centered setup panel.

    The right wall is intentionally absent.

    On terminal resize the old screen is explicitly cleared before
    the panel is moved/resized. The caller is then responsible for
    redrawing the complete page.
    """

    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.win = None

        self.h = 0
        self.w = 0
        self.top = 0
        self.left = 0

        self.screen_h = 0
        self.screen_w = 0

        self.recenter()

    def handle_resize(self):
        """
        Handle terminal resize event.

        Clears the entire terminal screen, recenters the panel, and
        prepares it for a full redraw. The caller must call the page's
        redraw() function after this to restore the content.
        """
        # Clear the entire terminal screen and mark for refresh
        # so that old pixels from the previous panel position are
        # removed from the physical terminal.
        self.stdscr.erase()
        self.stdscr.noutrefresh()

        # Recalculate panel geometry and reposition
        # This also clears stdscr again if geometry changed
        self.recenter()

        # Erase the panel window content
        if self.win is not None:
            self.win.erase()

    def recenter(self) -> bool:
        """
        Recalculate panel geometry.

        Returns True when the terminal geometry changed.
        The entire stdscr is cleared before moving the panel so that
        no pixels from the previous panel position remain visible.
        """
        screen_h, screen_w = self.stdscr.getmaxyx()

        h = min(PANEL_H, max(1, screen_h))
        w = min(PANEL_W, max(1, screen_w))

        top = max(0, (screen_h - h) // 2)
        left = max(0, (screen_w - w) // 2)

        changed = (
            self.win is None
            or self.h != h
            or self.w != w
            or self.top != top
            or self.left != left
            or self.screen_h != screen_h
            or self.screen_w != screen_w
        )

        if changed:
            # Remove everything rendered at the old terminal geometry.
            self.stdscr.erase()

        self.h = h
        self.w = w
        self.top = top
        self.left = left
        self.screen_h = screen_h
        self.screen_w = screen_w

        if self.win is None:
            self.win = curses.newwin(h, w, top, left)
            self.win.keypad(True)

        elif changed:
            try:
                self.win.resize(h, w)
                self.win.mvwin(top, left)
                self.win.keypad(True)
            except curses.error:
                # Some terminals reject a move/resize during SIGWINCH.
                # Recreate the window instead.
                self.win = curses.newwin(h, w, top, left)
                self.win.keypad(True)

        return changed

    def resized(self) -> bool:
        screen_h, screen_w = self.stdscr.getmaxyx()
        return (
            screen_h != self.screen_h
            or screen_w != self.screen_w
        )

    def refresh(self):
        self.win.noutrefresh()
        curses.doupdate()

    def getch(self):
        return self.win.getch()

    def _safe(self, row: int, col: int, text: str, attr=0):
        if not text:
            return

        if row < 0 or row >= self.h:
            return

        if col < 0 or col >= self.w:
            return

        max_len = self.w - col

        if max_len <= 0:
            return

        try:
            self.win.addstr(
                row,
                col,
                text[:max_len],
                attr,
            )
        except curses.error:
            pass

    def content_row(self, row: int) -> int:
        return 3 + row

    # ── Frame ─────────────────────────────────────────────────────────────────

    def draw_frame(
        self,
        page: Optional[int] = None,
        total: Optional[int] = None,
    ):
        if self.w < 2 or self.h < 2:
            return

        line_width = max(1, self.w - 1)

        # Top border.
        self._safe(
            0,
            0,
            "┌" + "─" * (line_width - 1),
            accent(),
        )

        # Header. Right wall intentionally absent.
        self._safe(
            1,
            0,
            "│",
            accent(),
        )

        title = " nx setup "

        self._safe(
            1,
            1,
            title,
            accent(),
        )

        counter = ""

        if page is not None and total is not None:
            counter = f"{page} / {total}"

        title_end = 1 + len(title)

        if counter:
            counter_col = max(
                title_end,
                self.w - len(counter),
            )

            gap = max(
                0,
                counter_col - title_end,
            )

            self._safe(
                1,
                title_end,
                "─" * gap,
                dim(),
            )

            self._safe(
                1,
                counter_col,
                counter,
                dim(),
            )

        else:
            self._safe(
                1,
                title_end,
                "─" * max(
                    0,
                    self.w - title_end - 1,
                ),
                dim(),
            )

        # Separator.
        self._safe(
            2,
            0,
            "├" + "─" * (line_width - 1),
            accent(),
        )

        # Left wall only.
        for row in range(3, self.h - 1):
            self._safe(
                row,
                0,
                "│",
                accent(),
            )

        # Bottom border.
        self._safe(
            self.h - 1,
            0,
            "└" + "─" * (line_width - 1),
            accent(),
        )

    # ── Text ──────────────────────────────────────────────────────────────────

    def text(self, row: int, text: str, attr=None):
        self._safe(
            self.content_row(row),
            INNER_PAD,
            text,
            normal() if attr is None else attr,
        )

    def bold(self, row: int, text: str):
        self.text(
            row,
            text,
            normal() | curses.A_BOLD,
        )

    def dim(self, row: int, text: str):
        self.text(row, text, dim())

    def accent(self, row: int, text: str):
        self.text(row, text, accent())

    def success(self, row: int, text: str):
        self.text(row, text, success())

    def error(self, row: int, text: str):
        self.text(row, text, error())

    def label(self, row: int, text: str):
        self.text(row, text, label())

    def clear_row(self, row: int):
        abs_row = self.content_row(row)

        if not (0 <= abs_row < self.h - 1):
            return

        try:
            self.win.move(abs_row, 1)
            self.win.clrtoeol()
        except curses.error:
            pass

        self._safe(
            abs_row,
            0,
            "│",
            accent(),
        )

    # ── Hints ─────────────────────────────────────────────────────────────────

    def draw_hints(
        self,
        hints: list[tuple[str, str]],
        row: int = 14,
    ):
        sep_row = self.content_row(row)
        hint_row = sep_row + 1

        self._safe(
            sep_row,
            0,
            "├" + "─" * max(0, self.w - 2),
            dim(),
        )

        col = INNER_PAD

        for key, description in hints:
            key_text = f" {key} "
            desc_text = f"{description}  "

            self._safe(
                hint_row,
                col,
                key_text,
                label(),
            )

            col += len(key_text)

            self._safe(
                hint_row,
                col,
                desc_text,
                dim(),
            )

            col += len(desc_text)

    def render(
        self,
        page: Optional[int] = None,
        total: Optional[int] = None,
        hints=None,
    ):
        self.win.erase()
        self.draw_frame(page, total)

        if hints is not None:
            self.draw_hints(hints)

        self.refresh()

    # ── Text input ────────────────────────────────────────────────────────────

    def input_field(
        self,
        row: int,
        prompt: str,
        default: str,
        validate_fn: Callable[[str], Optional[str]],
        redraw: Callable[[], None],
        error_row: Optional[int] = None,
    ) -> str:
        """
        Transparent text input.

        redraw() is called whenever the terminal is resized.
        It must redraw the complete page, not merely the input field.
        """

        if error_row is None:
            error_row = row + 2

        try:
            curses.curs_set(1)
        except curses.error:
            pass

        buf = list(default)
        cursor = len(buf)
        scroll = 0
        err = ""

        while True:
            if self.resized():
                self.recenter()

                # The old screen has been erased.
                # Rebuild the complete page.
                redraw()

            field_width = max(
                8,
                self.w - INNER_PAD - len(prompt) - 2,
            )

            cursor = max(
                0,
                min(cursor, len(buf)),
            )

            if cursor < scroll:
                scroll = cursor

            if cursor > scroll + field_width:
                scroll = cursor - field_width

            value = "".join(buf)
            visible = value[
                scroll:scroll + field_width
            ]

            self.clear_row(row)
            self.clear_row(error_row)

            abs_row = self.content_row(row)
            abs_error = self.content_row(error_row)

            prompt_col = INNER_PAD
            field_col = prompt_col + len(prompt) + 1

            self._safe(
                abs_row,
                prompt_col,
                prompt,
                dim(),
            )

            # Transparent input.
            self._safe(
                abs_row,
                field_col,
                visible,
                input_attr(),
            )

            if err:
                self._safe(
                    abs_error,
                    INNER_PAD,
                    err,
                    error(),
                )

            cursor_col = min(
                self.w - 1,
                field_col + (cursor - scroll),
            )

            try:
                self.win.move(
                    abs_row,
                    cursor_col,
                )
            except curses.error:
                pass

            self.refresh()

            key = self.getch()

            if key == curses.KEY_RESIZE:
                self.handle_resize()
                redraw()
                continue

            if key in (
                curses.KEY_ENTER,
                10,
                13,
            ):
                candidate = (
                    "".join(buf).strip()
                    or default
                )

                validation_error = validate_fn(
                    candidate
                )

                if validation_error:
                    err = validation_error
                    continue

                try:
                    curses.curs_set(0)
                except curses.error:
                    pass

                return candidate

            if key == 27:
                try:
                    curses.curs_set(0)
                except curses.error:
                    pass

                raise Back

            if key == 3:
                try:
                    curses.curs_set(0)
                except curses.error:
                    pass

                raise Quit

            if key in (
                curses.KEY_BACKSPACE,
                127,
                8,
            ):
                if cursor > 0:
                    del buf[cursor - 1]
                    cursor -= 1
                    err = ""

                continue

            if key == curses.KEY_DC:
                if cursor < len(buf):
                    del buf[cursor]
                    err = ""

                continue

            if key == curses.KEY_LEFT:
                cursor = max(0, cursor - 1)
                continue

            if key == curses.KEY_RIGHT:
                cursor = min(
                    len(buf),
                    cursor + 1,
                )
                continue

            if key == curses.KEY_HOME:
                cursor = 0
                continue

            if key == curses.KEY_END:
                cursor = len(buf)
                continue

            if 32 <= key <= 126:
                buf.insert(
                    cursor,
                    chr(key),
                )

                cursor += 1
                err = ""

    # ── Yes / No ──────────────────────────────────────────────────────────────

    def yn_choice(
        self,
        row: int,
        default: bool,
        redraw: Callable[[], None],
    ) -> bool:
        selected = default

        while True:
            if self.resized():
                self.recenter()
                redraw()

            self.clear_row(row)
            self.clear_row(row + 1)

            if selected:
                self._safe(
                    self.content_row(row),
                    INNER_PAD,
                    "▸ Yes",
                    success(),
                )

                self._safe(
                    self.content_row(row + 1),
                    INNER_PAD,
                    "  No",
                    dim(),
                )

            else:
                self._safe(
                    self.content_row(row),
                    INNER_PAD,
                    "  Yes",
                    dim(),
                )

                self._safe(
                    self.content_row(row + 1),
                    INNER_PAD,
                    "▸ No",
                    success(),
                )

            self.refresh()

            key = self.getch()

            if key == curses.KEY_RESIZE:
                self.handle_resize()
                redraw()
                continue

            if key in (
                curses.KEY_UP,
                ord("y"),
                ord("Y"),
            ):
                selected = True
                continue

            if key in (
                curses.KEY_DOWN,
                ord("n"),
                ord("N"),
            ):
                selected = False
                continue

            if key in (
                curses.KEY_ENTER,
                10,
                13,
            ):
                return selected

            if key == 27:
                raise Back

            if key == 3:
                raise Quit


# ─── Page creation ────────────────────────────────────────────────────────────

def create_panel(
    stdscr,
    page=None,
    total=None,
    hints=None,
):
    stdscr.erase()

    panel = Panel(stdscr)
    panel.render(
        page,
        total,
        hints,
    )

    return panel


# ─── Pages ────────────────────────────────────────────────────────────────────

def page_welcome(stdscr, page: int, total: int):
    hints = [
        ("Enter", "continue"),
        ("Esc", "quit"),
        ("Ctrl-C", "quit"),
    ]

    panel = create_panel(
        stdscr,
        page,
        total,
        hints,
    )

    def redraw():
        panel.win.erase()
        panel.draw_frame(page, total)
        panel.draw_hints(hints)

        panel.accent(1, "nx setup")
        panel.text(
            3,
            "nx will configure how your NixOS setup is",
        )
        panel.text(4, "organized.")
        panel.dim(
            6,
            "Settings will be saved to",
        )
        panel.dim(
            7,
            "~/.config/nx/config.toml",
        )

        panel.refresh()

    redraw()

    while True:
        key = panel.getch()

        if key == curses.KEY_RESIZE:
            panel.handle_resize()
            redraw()
            continue

        if key in (
            curses.KEY_ENTER,
            10,
            13,
        ):
            return

        if key in (27, 3):
            raise Quit


def page_configuration_path(
    stdscr,
    cfg: Config,
    page: int,
    total: int,
):
    hints = [
        ("Enter", "confirm"),
        ("Esc", "back"),
        ("Ctrl-C", "quit"),
    ]

    panel = create_panel(
        stdscr,
        page,
        total,
        hints,
    )

    def redraw():
        panel.win.erase()
        panel.draw_frame(page, total)
        panel.draw_hints(hints)

        panel.bold(
            1,
            "Where is your configuration.nix?",
        )
        panel.dim(
            2,
            f"default: {cfg.configuration_path}",
        )
        panel.dim(
            4,
            "This is the main NixOS configuration file.",
        )

        panel.refresh()

    redraw()

    cfg.configuration_path = panel.input_field(
        6,
        "path:",
        cfg.configuration_path,
        validate_nix_path,
        redraw,
        error_row=9,
    )


def page_flakes(
    stdscr,
    cfg: Config,
    page: int,
    total: int,
):
    hints = [
        ("↑↓ / Y N", "select"),
        ("Enter", "confirm"),
        ("Esc", "back"),
        ("Ctrl-C", "quit"),
    ]

    panel = create_panel(
        stdscr,
        page,
        total,
        hints,
    )

    def redraw():
        panel.win.erase()
        panel.draw_frame(page, total)
        panel.draw_hints(hints)

        panel.bold(
            1,
            "Do you use Nix Flakes?",
        )
        panel.dim(
            3,
            "Flakes provide reproducible inputs and outputs",
        )
        panel.dim(
            4,
            "for NixOS configurations and package sources.",
        )

        panel.refresh()

    redraw()

    cfg.flake_enabled = panel.yn_choice(
        6,
        default=cfg.flake_enabled,
        redraw=redraw,
    )


def page_flake_path(
    stdscr,
    cfg: Config,
    page: int,
    total: int,
):
    hints = [
        ("Enter", "confirm"),
        ("Esc", "back"),
        ("Ctrl-C", "quit"),
    ]

    panel = create_panel(
        stdscr,
        page,
        total,
        hints,
    )

    default_path = str(
        Path(cfg.configuration_path).parent
        / "flake.nix"
    )

    if (
        cfg.flake_path == "/etc/nixos/flake.nix"
        and default_path != cfg.flake_path
    ):
        cfg.flake_path = default_path

    def redraw():
        panel.win.erase()
        panel.draw_frame(page, total)
        panel.draw_hints(hints)

        panel.bold(
            1,
            "Where is your flake.nix?",
        )
        panel.dim(
            2,
            f"default: {cfg.flake_path}",
        )
        panel.dim(
            4,
            "This is the file containing your Flake inputs and outputs.",
        )

        panel.refresh()

    redraw()

    cfg.flake_path = panel.input_field(
        6,
        "path:",
        cfg.flake_path,
        validate_nix_path,
        redraw,
        error_row=9,
    )


def page_home_manager(
    stdscr,
    cfg: Config,
    page: int,
    total: int,
):
    hints = [
        ("↑↓ / Y N", "select"),
        ("Enter", "confirm"),
        ("Esc", "back"),
        ("Ctrl-C", "quit"),
    ]

    panel = create_panel(
        stdscr,
        page,
        total,
        hints,
    )

    def redraw():
        panel.win.erase()
        panel.draw_frame(page, total)
        panel.draw_hints(hints)

        panel.bold(
            1,
            "Do you use Home Manager?",
        )
        panel.dim(
            3,
            "Home Manager handles user-level packages",
        )
        panel.dim(
            4,
            "and configuration files.",
        )

        panel.refresh()

    redraw()

    cfg.home_manager_enabled = panel.yn_choice(
        6,
        default=cfg.home_manager_enabled,
        redraw=redraw,
    )


def page_home_manager_path(
    stdscr,
    cfg: Config,
    page: int,
    total: int,
):
    hints = [
        ("Enter", "confirm"),
        ("Esc", "back"),
        ("Ctrl-C", "quit"),
    ]

    panel = create_panel(
        stdscr,
        page,
        total,
        hints,
    )

    default_path = str(
        Path(cfg.configuration_path).parent
        / "home.nix"
    )

    if (
        cfg.home_manager_path == "/etc/nixos/home.nix"
        and default_path != cfg.home_manager_path
    ):
        cfg.home_manager_path = default_path

    def redraw():
        panel.win.erase()
        panel.draw_frame(page, total)
        panel.draw_hints(hints)

        panel.bold(
            1,
            "Where is your home.nix?",
        )
        panel.dim(
            2,
            f"default: {cfg.home_manager_path}",
        )
        panel.dim(
            4,
            "This is the main Home Manager configuration file.",
        )

        panel.refresh()

    redraw()

    cfg.home_manager_path = panel.input_field(
        6,
        "path:",
        cfg.home_manager_path,
        validate_nix_path,
        redraw,
        error_row=9,
    )


def page_unstable_variable(
    stdscr,
    cfg: Config,
    page: int,
    total: int,
):
    hints = [
        ("Enter", "confirm"),
        ("Esc", "back"),
        ("Ctrl-C", "quit"),
    ]

    panel = create_panel(
        stdscr,
        page,
        total,
        hints,
    )

    def redraw():
        panel.win.erase()
        panel.draw_frame(page, total)
        panel.draw_hints(hints)

        panel.bold(
            1,
            "What variable name for nixpkgs-unstable?",
        )
        panel.dim(
            3,
            f"default: {cfg.unstable_variable}",
        )
        panel.dim(
            4,
            "Examples: unstable, unstablePkgs, myPkgs",
        )

        panel.refresh()

    redraw()

    cfg.unstable_variable = panel.input_field(
        6,
        "name:",
        cfg.unstable_variable,
        validate_var_name,
        redraw,
        error_row=9,
    )


# ─── Review ───────────────────────────────────────────────────────────────────

def render_review(
    panel: Panel,
    cfg: Config,
    page: int,
    total: int,
):
    hints = [
        ("Enter", "save"),
        ("Esc", "back"),
        ("Ctrl-C", "quit"),
    ]

    panel.win.erase()
    panel.draw_frame(page, total)
    panel.draw_hints(hints)

    row = 1

    panel.label(
        row,
        "configuration.nix",
    )
    row += 1

    panel.text(
        row,
        cfg.configuration_path,
    )
    row += 2

    panel.label(row, "Flakes")
    row += 1

    panel.success(
        row,
        "enabled"
        if cfg.flake_enabled
        else "disabled",
    )
    row += 1

    if cfg.flake_enabled:
        panel.text(
            row,
            cfg.flake_path,
        )
        row += 2
    else:
        row += 1

    panel.label(row, "Home Manager")
    row += 1

    panel.success(
        row,
        "enabled"
        if cfg.home_manager_enabled
        else "disabled",
    )
    row += 1

    if cfg.home_manager_enabled:
        panel.text(
            row,
            cfg.home_manager_path,
        )
        row += 2
    else:
        row += 1

    panel.label(
        row,
        "Unstable variable",
    )
    row += 1

    panel.text(
        row,
        cfg.unstable_variable,
    )

    panel.refresh()


def page_review(
    stdscr,
    cfg: Config,
    page: int,
    total: int,
):
    panel = Panel(stdscr)

    render_review(
        panel,
        cfg,
        page,
        total,
    )

    while True:
        key = panel.getch()

        if key == curses.KEY_RESIZE:
            panel.handle_resize()
            render_review(panel, cfg, page, total)
            continue

        if key in (curses.KEY_ENTER, 10, 13):
            return

        if key == 27:
            raise Back

        if key == 3:
            raise Quit


# ─── Done ────────────────────────────────────────────────────────────────────

def page_done(stdscr):
    hints = [
        ("Enter", "exit"),
        ("q", "quit"),
    ]

    panel = create_panel(
        stdscr,
        hints=hints,
    )

    def redraw():
        panel.win.erase()
        panel.draw_frame()
        panel.draw_hints(hints)

        panel.success(3, "Configuration saved.")
        panel.dim(5, str(CONFIG_FILE))

        panel.refresh()

    redraw()

    while True:
        key = panel.getch()

        if key == curses.KEY_RESIZE:
            panel.handle_resize()
            redraw()
            continue

        if key in (
            curses.KEY_ENTER,
            10,
            13,
            ord("q"),
            ord("Q"),
        ):
            return

        if key == 3:
            return


# ─── Wizard ──────────────────────────────────────────────────────────────────

def build_pages(stdscr, cfg: Config):
    pages = [
        (
            "welcome",
            lambda page, total:
                page_welcome(
                    stdscr,
                    page,
                    total,
                ),
        ),
        (
            "configuration_path",
            lambda page, total:
                page_configuration_path(
                    stdscr,
                    cfg,
                    page,
                    total,
                ),
        ),
        (
            "flakes",
            lambda page, total:
                page_flakes(
                    stdscr,
                    cfg,
                    page,
                    total,
                ),
        ),
    ]

    if cfg.flake_enabled:
        pages.append(
            (
                "flake_path",
                lambda page, total:
                    page_flake_path(
                        stdscr,
                        cfg,
                        page,
                        total,
                    ),
            )
        )

    pages.append(
        (
            "home_manager",
            lambda page, total:
                page_home_manager(
                    stdscr,
                    cfg,
                    page,
                    total,
                ),
        )
    )

    if cfg.home_manager_enabled:
        pages.append(
            (
                "home_manager_path",
                lambda page, total:
                    page_home_manager_path(
                        stdscr,
                        cfg,
                        page,
                        total,
                    ),
            )
        )

    pages.extend(
        [
            (
                "unstable_variable",
                lambda page, total:
                    page_unstable_variable(
                        stdscr,
                        cfg,
                        page,
                        total,
                    ),
            ),
            (
                "review",
                lambda page, total:
                    page_review(
                        stdscr,
                        cfg,
                        page,
                        total,
                    ),
            ),
        ]
    )

    return pages


def _setup(stdscr) -> dict:
    init_colors()

    # Make Esc responsive instead of waiting for an escape sequence.
    curses.set_escdelay(25)

    try:
        curses.curs_set(0)
    except curses.error:
        pass

    stdscr.keypad(True)
    stdscr.timeout(-1)

    cfg = Config()
    index = 0

    while True:
        pages = build_pages(
            stdscr,
            cfg,
        )

        if index >= len(pages):
            break

        name, page_fn = pages[index]

        total = len(pages)
        page = index + 1

        try:
            page_fn(
                page,
                total,
            )

            index += 1

        except Back:
            if index > 0:
                index -= 1

        except Quit:
            raise

        except curses.error:
            # Terminal may resize while curses is drawing.
            # Restart the current page cleanly.
            continue

    return {
        "configuration_path":
            cfg.configuration_path,

        "flake_enabled":
            cfg.flake_enabled,

        "flake_path":
            cfg.flake_path,

        "home_manager_enabled":
            cfg.home_manager_enabled,

        "home_manager_path":
            cfg.home_manager_path,

        "unstable_variable":
            cfg.unstable_variable,
    }


def first_setup() -> Optional[dict]:
    """
    Run the initial setup wizard.

    Configuration is saved only after the wizard reaches
    the end successfully. Cancelling with Ctrl-C or quitting
    does not write configuration.
    """
    try:
        result = curses.wrapper(_setup)

    except Quit:
        return None

    save_config(**result)

    curses.wrapper(page_done)

    return result


if __name__ == "__main__":
    first_setup()
