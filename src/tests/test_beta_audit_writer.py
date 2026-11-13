"""Beta audit 1/3 — writer adversarial tests.

READ-ONLY audit: asserts CORRECT behavior; a failed check here documents a
bug, not a test error. Currently every check passes.

Covers: silent no-op paths, format detection, formatting preservation,
duplicates, removal, external imports, malformed input, boundary sizes,
and a formatting-variation property check.
"""
import inspect
import time
from pathlib import Path

import pytest

from core.writer import add_package, remove_package

SYSTEM = "environment.systemPackages"
HOME = "home.packages"


# ── [A] Silent no-op paths (critical correctness property) ──────────────────

@pytest.mark.parametrize("content,block,predicate", [
    ('{ pkgs, ... }:\n{\n  home.packages = [ ];\n}\n', HOME,
     lambda r: "htop" in r.content),
    ('{ pkgs, ... }:\n{\n  environment.systemPackages = [ ];\n}\n', SYSTEM,
     lambda r: "htop" in r.content),
    ('''{ pkgs, ... }:
{
  home.packages = [
    pkgs.git
  ];
  environment.systemPackages = with pkgs; [
    vim
  ];
}
''', HOME, lambda r: "htop" in r.content),
    ('''{ pkgs, ... }:
{
  environment.systemPackages = [
    pkgs.vim
  ];
  home.packages = with pkgs; [
    git
  ];
}
''', SYSTEM, lambda r: "htop" in r.content),
    ('{ pkgs, ... }:\n{\n  # home.packages is managed manually\n  home.username = "u";\n}\n',
     HOME, lambda r: "home.packages = " in r.content and "htop" in r.content),
    ('''{ pkgs, ... }:
{
  # environment.systemPackages = [ old-style ]
  environment.systemPackages = with pkgs; [
    git
  ];
}
''', SYSTEM,
     lambda r: "htop" in r.content
     and "# environment.systemPackages = [ old-style htop" not in r.content),
], ids=[
    "A1 empty home.packages: success ⇒ htop present",
    "A2 empty systemPackages: success ⇒ htop present",
    "A3 home plain + later 'with pkgs': success ⇒ htop added",
    "A4 system plain + later 'with pkgs': success ⇒ htop added",
    "A5 comment-only mention: no silent success without a real block",
    "A6 decoy comment block: insertion must hit the REAL block",
])
def test_add_package_never_reports_success_without_adding(content, block, predicate):
    r = add_package(content, "htop", Path("/tmp"), block)
    assert r.status != "success" or predicate(r), \
        f"status={r.status}, added={predicate(r)}"


# ── [B] Formatting preservation ─────────────────────────────────────────────

def test_comment_inside_block_preserved():
    b1 = '''{ pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    git   # vcs
    vim
  ];
}
'''
    r = add_package(b1, "htop", Path("/tmp"), SYSTEM)
    assert r.status == "success" and "# vcs" in r.content
    assert "git" in r.content and "vim" in r.content


def test_tab_indentation_matched():
    b2 = '{ pkgs, ... }:\n{\n\thome.packages = with pkgs; [\n\t\tgit\n\t];\n}\n'
    r = add_package(b2, "htop", Path("/tmp"), HOME)
    assert r.status == "success" and "\t\thtop" in r.content, repr(r.content[:80])


# ── [C] Duplicates ──────────────────────────────────────────────────────────

def test_adding_existing_package_does_not_duplicate():
    c1 = '{ pkgs, ... }:\n{\n  environment.systemPackages = with pkgs; [\n    git\n  ];\n}\n'
    r1 = add_package(c1, "git", Path("/tmp"), SYSTEM)
    r2 = add_package(r1.content, "git", Path("/tmp"), SYSTEM)
    count = r2.content.count("git")
    assert r2.status != "success" or count == 1, \
        f"status={r2.status}, occurrences={count}"


# ── [D] Removal ─────────────────────────────────────────────────────────────

def test_remove_existing_keeps_others():
    d1 = '{ pkgs, ... }:\n{\n  home.packages = with pkgs; [\n    git\n    vim\n  ];\n}\n'
    out, found = remove_package(d1, "git", Path("/tmp"), HOME)
    assert found and "git" not in out and "vim" in out


def test_remove_nonexistent_unchanged():
    d1 = '{ pkgs, ... }:\n{\n  home.packages = with pkgs; [\n    git\n    vim\n  ];\n}\n'
    out, found = remove_package(d1, "nonexistent", Path("/tmp"), HOME)
    assert not found and out == d1


def test_remove_pkgs_prefixed_line_by_bare_name():
    d1 = '{ pkgs, ... }:\n{\n  home.packages = with pkgs; [\n    git\n    vim\n  ];\n}\n'
    out, found = remove_package(d1.replace("git", "pkgs.git"), "git", Path("/tmp"), HOME)
    assert found and "pkgs.git" not in out


def test_remove_line_with_trailing_comment():
    d1 = '{ pkgs, ... }:\n{\n  home.packages = with pkgs; [\n    git\n    vim\n  ];\n}\n'
    d4 = d1.replace("    git", "    git # note")
    out, found = remove_package(d4, "git", Path("/tmp"), HOME)
    assert found


# ── [E] External imports ────────────────────────────────────────────────────

def test_external_import_unsupported_and_untouched(tmp_path):
    (tmp_path / "pkgs.nix").write_text(
        '{\n  environment.systemPackages = with pkgs; [\n    git\n  ];\n}\n')
    host = '{ pkgs, ... }:\n{\n  environment.systemPackages = import ./pkgs.nix;\n}\n'
    r = add_package(host, "htop", tmp_path, SYSTEM)
    ext = (tmp_path / "pkgs.nix").read_text()
    assert r.status == "unsupported_external"
    assert r.content == host
    assert "htop" not in ext


def test_relative_parent_import_unsupported_and_untouched(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "pkgs.nix").write_text(
        '{\n  environment.systemPackages = with pkgs; [\n    git\n  ];\n}\n')
    host = '{ pkgs, ... }:\n{\n  environment.systemPackages = import ../sub/pkgs.nix;\n}\n'
    r = add_package(host, "htop", tmp_path, SYSTEM)
    ext = (sub / "pkgs.nix").read_text()
    assert r.status == "unsupported_external"
    assert r.content == host
    assert "htop" not in ext


# ── [F] Malformed input ─────────────────────────────────────────────────────

def test_unclosed_bracket_not_clean_success():
    f1 = '{ pkgs, ... }:\n{\n  home.packages = with pkgs; [\n    git\n}\n'
    r = add_package(f1, "htop", Path("/tmp"), HOME)
    assert r.status != "success" or r.content == f1, \
        f"status={r.status}, mangled={r.content != f1}"


def test_empty_file_not_clean_success():
    r = add_package("", "htop", Path("/tmp"), HOME)
    assert r.status != "success" or r.content.strip() != "", \
        f"status={r.status}, produced={r.content!r:.60}"


# ── [G] Boundary size ───────────────────────────────────────────────────────

def test_thousand_package_block_add_and_remove_under_two_seconds():
    many = ", ".join(f"p{i}" for i in range(1000))
    g1 = '{ pkgs, ... }:\n{\n  home.packages = with pkgs; [\n    ' + many + '\n  ];\n}\n'
    t0 = time.time()
    r = add_package(g1, "htop", Path("/tmp"), HOME)
    out, found = remove_package(r.content, "htop", Path("/tmp"), HOME)
    dt = time.time() - t0
    assert found and dt < 2.0 and "p999" in out, f"took {dt:.2f}s"


# ── [H] Formatting-variation property ──────────────────────────────────────

@pytest.mark.parametrize("label,content", [
    ("2-space-indent", '{ pkgs, ... }:\n{\n  home.packages = [ ];\n}\n'),
    ("4-space-indent", '{ pkgs, ... }:\n    {\n    home.packages = [ ];\n    }\n'),
    ("no-spaces", '{pkgs,...}:{home.packages=[];}'),
    ("newline-in-list", '{ pkgs, ... }:\n{\n  home.packages = [\n\n  ];\n}\n'),
    ("trailing-space-eq", '{ pkgs, ... }:\n{\n  home.packages  =  [ ];\n}\n'),
    ("block-last-no-nl", '{ pkgs, ... }:\n{\n  home.packages = [ ];\n}'),
    ("with-pkgs-same-line", '{ pkgs, ... }:\n{\n  home.packages = with pkgs; [ git ];\n}\n'),
    ("comment-above-block", '{ pkgs, ... }:\n{\n  # packages\n  home.packages = [ ];\n}\n'),
], ids=[
    "2-space-indent",
    "4-space-indent",
    "no-spaces",
    "newline-in-list",
    "trailing-space-eq",
    "block-last-no-nl",
    "with-pkgs-same-line",
    "comment-above-block",
])
def test_no_silent_noop_across_formatting_variations(label, content):
    r = add_package(content, "htop", Path("/tmp"), HOME)
    assert r.status != "success" or "htop" in r.content, \
        f"{label}: status={r.status} added={'htop' in r.content}"


# ── [I] Dead-code evidence (informational) ──────────────────────────────────

def test_empty_never_reaches_a_handler():
    src = inspect.getsource(add_package)
    assert "add_package_empty(" not in src
    assert "unsupported_" in src
