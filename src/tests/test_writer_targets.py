"""Target-aware writer regression tests.

Verifies that the parameterized writer operates correctly on BOTH
environment.systemPackages (SYSTEM) and home.packages (HOME), and that
the default (no block argument) preserves historical SYSTEM behavior
byte-for-byte.

Migrated from the original script harness; every ``check`` maps 1:1 to a
collected pytest test instance.
"""
from pathlib import Path

import pytest

from core.writer import (
    add_package, remove_package, is_package_exists, detect_format,
    add_flake_package, add_flake_overlay, remove_flake_reference,
    resolve_package_block,
)

SYSTEM = "environment.systemPackages"
HOME = "home.packages"

SYS_WITH_PKGS = '''{ pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    git
  ];
}
'''

HOME_WITH_PKGS = '''{ pkgs, ... }:
{
  home.username = "u";
  home.packages = with pkgs; [
    git
  ];
}
'''

HOME_PLAIN = '''{ pkgs, ... }:
{
  home.packages = [
    pkgs.git
  ];
}
'''

HOME_MISSING = '''{ pkgs, ... }:
{
  home.username = "u";
}
'''

SYS_EMPTY = "{ pkgs, ... }:\n{\n  environment.systemPackages = [ ];\n}\n"
HOME_EMPTY = "{ pkgs, ... }:\n{\n  home.packages = [ ];\n}\n"

FLAKE_REF_LINE = "inputs.test-flake.packages.${pkgs.stdenv.hostPlatform.system}.default"

HOME_WITH = '''{ pkgs, ... }:
{
  home.packages = with pkgs; [
    git
  ];
}
'''

HOME_PLAIN_WITH = '''{ pkgs, ... }:
{
  home.packages = [
    pkgs.git
  ];
}
'''

OVERLAY_EXISTING = '''{ config, pkgs, inputs, ... }:
{
  nixpkgs.overlays = [
    inputs.other-flake.overlays.default
  ];
}
'''

NO_OVERLAY_BLOCK = '''{ config, pkgs, inputs, ... }:
{
  environment.systemPackages = with pkgs; [
    git
  ];
}
'''

OVERLAY_INSTALLED = '''{ config, pkgs, inputs, ... }:
{
  nixpkgs.overlays = [
    inputs.claude-desktop-nix.overlays.default
  ];
}
'''

MIXED = '''{ config, pkgs, inputs, ... }:
{
  nixpkgs.overlays = [
    inputs.claude-desktop-nix.overlays.default
    inputs.other-flake.overlays.default
  ];
  environment.systemPackages = with pkgs; [
    inputs.zen-browser.packages.${pkgs.stdenv.hostPlatform.system}.default
  ];
}
'''

PKG_CONTENT = '''{ config, pkgs, inputs, ... }:
{
  environment.systemPackages = with pkgs; [
    inputs.zen-browser.packages.${pkgs.stdenv.hostPlatform.system}.default
  ];
}
'''


# ── [1] detect_format — both blocks ─────────────────────────────────────────

@pytest.mark.parametrize("content,block,expected", [
    (SYS_WITH_PKGS, None, "with_pkgs"),
    (SYS_WITH_PKGS, SYSTEM, "with_pkgs"),
    (HOME_WITH_PKGS, HOME, "with_pkgs"),
    (HOME_PLAIN, HOME, "explicit_pkgs"),
    (HOME_MISSING, HOME, "missing"),
    (HOME_WITH_PKGS, None, "missing"),
    (SYS_WITH_PKGS, HOME, "missing"),
], ids=[
    "system with_pkgs",
    "system with_pkgs (explicit block arg)",
    "home with_pkgs",
    "home plain list → explicit_pkgs",
    "home missing block",
    "default block ignores home.packages (missing for SYSTEM)",
    "home block ignored when asking SYSTEM",
])
def test_detect_format_both_blocks(content, block, expected):
    if block is None:
        assert detect_format(content) == expected
    else:
        assert detect_format(content, block) == expected


# ── [2] add_package — SYSTEM (default, regression) ──────────────────────────

def test_add_package_system_default():
    result = add_package(SYS_WITH_PKGS, "htop", Path("/tmp"))
    assert result.status == "success"
    assert "htop" in result.content
    assert "git" in result.content


# ── [3] add_package — HOME with_pkgs ────────────────────────────────────────

def test_add_package_home_with_pkgs():
    result = add_package(HOME_WITH_PKGS, "htop", Path("/tmp"), HOME)
    assert result.status == "success"
    assert "htop" in result.content
    assert "git" in result.content
    assert "home.username" in result.content


def test_add_package_home_leaves_system_packages_untouched():
    both = SYS_WITH_PKGS.replace("}", "  home.packages = with pkgs; [ vim ];\n}")
    result = add_package(both, "htop", Path("/tmp"), HOME)
    assert result.content.count("htop") == 1
    assert "environment.systemPackages" in result.content


# ── [4] add_package — HOME plain list (explicit pkgs) ───────────────────────

def test_add_package_home_plain_list():
    result = add_package(HOME_PLAIN, "htop", Path("/tmp"), HOME)
    assert result.status == "success"
    assert "pkgs.htop" in result.content
    assert "pkgs.git" in result.content


# ── [5] add_package — HOME block missing ────────────────────────────────────

def test_add_package_home_missing_block():
    result = add_package(HOME_MISSING, "htop", Path("/tmp"), HOME)
    assert result.status == "unsupported_missing"
    assert result.content == HOME_MISSING
    assert "home.packages" not in result.content
    assert "environment.systemPackages" not in result.content


# ── [6] remove_package — both targets ───────────────────────────────────────

def test_remove_package_system():
    out, found = remove_package(SYS_WITH_PKGS, "git", Path("/tmp"))
    assert found
    assert "git" not in out


def test_remove_package_home_with_pkgs():
    out, found = remove_package(HOME_WITH_PKGS, "git", Path("/tmp"), HOME)
    assert found
    assert "git" not in out
    assert "home.username" in out


def test_remove_package_home_plain_pkgs_form():
    out, found = remove_package(HOME_PLAIN, "pkgs.git", Path("/tmp"), HOME)
    assert found


def test_remove_package_not_found_keeps_content():
    out, found = remove_package(HOME_WITH_PKGS, "nonexistent", Path("/tmp"), HOME)
    assert not found
    assert out == HOME_WITH_PKGS


def test_remove_package_home_leaves_system_packages():
    both = SYS_WITH_PKGS.replace("}", "  home.packages = with pkgs; [ git ];\n}")
    out, found = remove_package(both, "git", Path("/tmp"), HOME)
    assert found
    assert out.count("git") >= 1
    assert "environment.systemPackages" in out


# ── [7] is_package_exists — both targets ────────────────────────────────────

@pytest.mark.parametrize("content,name,block,expected", [
    (SYS_WITH_PKGS, "git", None, True),
    (SYS_WITH_PKGS, "htop", None, False),
    (HOME_WITH_PKGS, "git", HOME, True),
    (HOME_WITH_PKGS, "htop", HOME, False),
    (HOME_WITH_PKGS, "git", None, False),
    (SYS_WITH_PKGS, "git", HOME, False),
], ids=[
    "system: detects git",
    "system: rejects missing",
    "home: detects git",
    "home: rejects missing",
    "home: SYSTEM query on home-only file → False",
    "home: HOME query on system-only file → False",
])
def test_is_package_exists_both_targets(content, name, block, expected):
    if block is None:
        assert is_package_exists(content, name, Path("/tmp")) is expected
    else:
        assert is_package_exists(content, name, Path("/tmp"), block) is expected


# ── [8] empty blocks → unsupported_empty (Beta contract) ────────────────────

def test_add_package_system_empty_block():
    result = add_package(SYS_EMPTY, "htop", Path("/tmp"))
    assert result.status == "unsupported_empty"
    assert result.content == SYS_EMPTY


def test_add_package_home_empty_block():
    result = add_package(HOME_EMPTY, "htop", Path("/tmp"), HOME)
    assert result.status == "unsupported_empty"
    assert result.content == HOME_EMPTY
    assert "environment.systemPackages" not in result.content


# ── [9] add_flake_package — home.packages with-pkgs fix ─────────────────────

def test_add_flake_package_home_with_pkgs():
    out = add_flake_package(HOME_WITH, "test-flake", "default")
    assert "inputs.test-flake.packages" in out.content
    assert out.status == "success"
    assert "git" in out.content


def test_add_flake_package_home_plain_list():
    out = add_flake_package(HOME_PLAIN_WITH, "test-flake", "default")
    assert "inputs.test-flake.packages" in out.content
    assert out.status == "success"
    added_line = [l for l in out.content.split("\n") if "inputs.test-flake.packages" in l]
    assert bool(added_line)
    assert added_line[0].strip() == FLAKE_REF_LINE


def test_add_flake_package_falls_back_to_system():
    out = add_flake_package(SYS_WITH_PKGS, "test-flake", "default")
    assert "inputs.test-flake.packages" in out.content
    assert "environment.systemPackages" in out.content
    assert out.status == "success"


# ── [10] default argument ≡ explicit SYSTEM (byte-identical) ────────────────

@pytest.mark.parametrize("fn_name,fn,extra", [
    ("add_package", add_package, ("htop",)),
    ("remove_package", remove_package, ("git",)),
    ("is_package_exists", is_package_exists, ("git",)),
    ("detect_format", detect_format, ()),
], ids=[
    "add_package: default == explicit SYSTEM",
    "remove_package: default == explicit SYSTEM",
    "is_package_exists: default == explicit SYSTEM",
    "detect_format: default == explicit SYSTEM",
])
def test_default_argument_equals_explicit_system(fn_name, fn, extra):
    if fn_name == "detect_format":
        assert fn(SYS_WITH_PKGS) == fn(SYS_WITH_PKGS, SYSTEM)
    else:
        assert fn(SYS_WITH_PKGS, *extra, Path("/tmp")) == \
            fn(SYS_WITH_PKGS, *extra, Path("/tmp"), SYSTEM)


# ── [11] add_flake_overlay — inputs. namespace ──────────────────────────────

def test_add_flake_overlay_existing_block():
    out = add_flake_overlay(OVERLAY_EXISTING, "claude-desktop-nix", "default")
    assert "inputs.claude-desktop-nix.overlays.default" in out
    assert "claude-desktop-nix.overlays" not in out.replace(
        "inputs.claude-desktop-nix.overlays", "")
    assert "inputs.other-flake.overlays.default" in out


def test_add_flake_overlay_new_block():
    out = add_flake_overlay(NO_OVERLAY_BLOCK, "claude-desktop-nix", "default")
    assert "nixpkgs.overlays = [" in out
    assert "inputs.claude-desktop-nix.overlays.default" in out
    assert "claude-desktop-nix.overlays" not in out.replace(
        "inputs.claude-desktop-nix.overlays", "")


# ── [12] remove_flake_reference — overlay removal ───────────────────────────

def test_remove_flake_overlay_reference():
    out, found = remove_flake_reference(OVERLAY_INSTALLED, "claude-desktop-nix")
    assert found
    assert "claude-desktop-nix" not in out
    assert "nixpkgs.overlays = [" in out


def test_remove_flake_overlay_from_mixed():
    out, found = remove_flake_reference(MIXED, "claude-desktop-nix")
    assert found
    assert "claude-desktop-nix" not in out
    assert "inputs.other-flake.overlays.default" in out
    assert "inputs.zen-browser.packages.${pkgs.stdenv.hostPlatform.system}.default" in out


# ── [13] package references unchanged (regression) ──────────────────────────

def test_remove_flake_package_reference_by_name():
    out, found = remove_flake_reference(PKG_CONTENT, "zen-browser")
    assert found
    assert "zen-browser" not in out


def test_remove_flake_package_does_not_match_other_flakes():
    out, found = remove_flake_reference(PKG_CONTENT, "claude-desktop-nix")
    assert not found
    assert out == PKG_CONTENT


# ── SYSTEM/HOME target behavior unchanged (Step 3/4 regression) ─────────────

def test_add_flake_overlay_system_preserves_system_packages():
    sys_with_overlay = SYS_WITH_PKGS.replace(
        "}", "  nixpkgs.overlays = [\n    inputs.repo.overlays.default\n  ];\n}")
    out = add_flake_overlay(sys_with_overlay, "new-flake", "default")
    assert "environment.systemPackages" in out
    assert "git" in out


def test_add_flake_overlay_home_preserves_home_packages():
    home_with_overlay = HOME_WITH_PKGS.replace(
        "}", "  nixpkgs.overlays = [\n    inputs.repo.overlays.default\n  ];\n}")
    out = add_flake_overlay(home_with_overlay, "new-flake", "default")
    assert "home.packages" in out
    assert "git" in out


# ── [14] overlay insertion formatting (regression) ──────────────────────────

@pytest.mark.parametrize("content,expected", [
    ('{ config, pkgs, inputs, ... }:\n{\n  nixpkgs.overlays = [];\n}\n',
     "  nixpkgs.overlays = [\n    inputs.example.overlays.default\n  ];\n"),
    ('{ config, pkgs, inputs, ... }:\n{\n  nixpkgs.overlays = [\n  ];\n}\n',
     "  nixpkgs.overlays = [\n    inputs.example.overlays.default\n  ];\n"),
    ('{ config, pkgs, inputs, ... }:\n{\n  nixpkgs.overlays = [\n'
     '    inputs.other.overlays.default\n  ];\n}\n',
     "    inputs.other.overlays.default\n    inputs.example.overlays.default\n"),
], ids=[
    "inline []: expanded to a proper block",
    "empty multiline: entry indented to 4",
    "existing entry: sibling preserved + new entry aligned at 4 spaces",
])
def test_add_flake_overlay_block_formatting(content, expected):
    out = add_flake_overlay(content, "example", "default")
    assert expected in out


@pytest.mark.parametrize("content", [
    '{ config, pkgs, inputs, ... }:\n{\n  nixpkgs.overlays = [];\n}\n',
    '{ config, pkgs, inputs, ... }:\n{\n  nixpkgs.overlays = [\n  ];\n}\n',
    ('{ config, pkgs, inputs, ... }:\n{\n  nixpkgs.overlays = [\n'
     '    inputs.other.overlays.default\n  ];\n}\n'),
], ids=[
    "inline []: ']' not left at column 0",
    "empty multiline: ']' not left at column 0",
    "existing entry: ']' not left at column 0",
])
def test_add_flake_overlay_closing_bracket_indented(content):
    out = add_flake_overlay(content, "example", "default")
    assert "\n];" not in out


def test_add_flake_overlay_no_list_creates_block():
    content = '{ config, pkgs, inputs, ... }:\n{\n  system.stateVersion = "26.05";\n}\n'
    out = add_flake_overlay(content, "example", "default")
    assert "  nixpkgs.overlays = [\n    inputs.example.overlays.default\n  ];\n" in out
    assert out.rstrip().endswith("];\n}") or out.rstrip().endswith("];\n}\n".rstrip())


@pytest.mark.parametrize("content,inserted_after,comment_intact", [
    ('{ pkgs, ... }:\n{\n  a = 1;\n}\n# note with } brace\n',
     "  a = 1;\n  nixpkgs.overlays = [", "# note with } brace"),
    ('{ pkgs, ... }:\n{\n  b = "contains } brace";\n}\n',
     '  b = "contains } brace";\n  nixpkgs.overlays = [', None),
    ("{ pkgs, ... }:\n{\n  b = ''\n    text } here\n  '';\n}\n",
     "  '';\n  nixpkgs.overlays = [", None),
], ids=[
    "'}' in comment: block inserted inside the real attrset",
    "'}' in string: block inserted inside the real attrset",
    "'}' in indented string: block inserted inside the real attrset",
])
def test_add_flake_overlay_anchor_safety(content, inserted_after, comment_intact):
    out = add_flake_overlay(content, "example", "default")
    assert inserted_after in out
    assert "\n];" not in out
    if comment_intact is not None:
        assert out.rstrip().endswith(comment_intact)


def test_add_flake_overlay_closing_bracket_in_string():
    content = ('{ pkgs, ... }:\n{\n  nixpkgs.overlays = [\n'
               '    inputs.other.overlays.default\n'
               '  ];\n  note = "text with ] bracket";\n}\n')
    out = add_flake_overlay(content, "example", "default")
    assert "    inputs.other.overlays.default\n    inputs.example.overlays.default\n  ];\n" in out
    assert 'note = "text with ] bracket";' in out


def test_add_flake_overlay_duplicate_is_noop():
    once = add_flake_overlay(
        '{ config, pkgs, inputs, ... }:\n{\n  nixpkgs.overlays = [];\n}\n',
        "example", "default")
    assert add_flake_overlay(once, "example", "default") == once


# --- resolve_package_block -------------------------------------------------
#
# The block a write targets must come from the same decision as the target
# FILE. Before this helper existed, the non-flake install path called
# add_package() without a block, so detect_format() looked for
# environment.systemPackages inside home.nix, reported an unsupported
# format, rolled back and issued no rebuild (defect E2).

BARE = '''{ pkgs, ... }:
{
}
'''

EMPTY_HOME = '''{ pkgs, ... }:
{
  home.packages = [ ];
}
'''


def test_resolve_block_explicit_wins():
    """An explicit block always wins, whichever block the file contains."""
    assert resolve_package_block(HOME_WITH_PKGS, SYSTEM) == SYSTEM
    assert resolve_package_block(SYS_WITH_PKGS, HOME) == HOME


def test_resolve_block_auto_prefers_home():
    """Without an explicit block, a present home block is chosen."""
    assert resolve_package_block(HOME_WITH_PKGS, None) == HOME
    assert resolve_package_block(HOME_PLAIN, None) == HOME


def test_resolve_block_auto_falls_back_to_system():
    """Only a system block, or neither block, resolves to the system block."""
    assert resolve_package_block(SYS_WITH_PKGS, None) == SYSTEM
    assert resolve_package_block(BARE, None) == SYSTEM


def test_resolve_block_keeps_unsupported_home():
    """A home block in an unsupported format is still chosen.

    The unsupported status has to surface; a silent fallback to the system
    block would hide it and write into the wrong place.
    """
    assert detect_format(EMPTY_HOME, HOME) == "empty"
    assert resolve_package_block(EMPTY_HOME, None) == HOME


def test_add_flake_package_auto_targets_home():
    """The flake path keeps its documented auto-detect through the helper."""
    result = add_flake_package(HOME_WITH_PKGS, "repo", "vim")
    assert result.status == "success"
    assert "inputs.repo.packages" in result.content
    assert "home.packages" in result.content


def test_add_flake_package_explicit_block_wins():
    """An explicit block on the flake path is honoured, home present or not."""
    result = add_flake_package(HOME_WITH_PKGS, "repo", "vim", block=SYSTEM)
    assert result.status == "unsupported_missing"
