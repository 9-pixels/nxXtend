"""Writer format contract tests.

Covers the full chain: detect_format → SUPPORTED_FORMATS gate →
add_package result → add_flake_package → executor → main/UI boundary.

Beta contract: only `with_pkgs` and `explicit_pkgs` may be modified.
empty / missing / external / unknown are detected but never mutated.

Migrated from the original script harness; every ``check`` maps 1:1 to a
collected pytest test instance.
"""
import inspect
import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.target import Target
from core.writer import (
    detect_format, add_package, remove_package,
    is_package_exists, add_flake_package, add_flake, AddResult,
)

SYSTEM = "environment.systemPackages"
HOME = "home.packages"

SYS_WPKGS = '{ pkgs, ... }:\n{\n  environment.systemPackages = with pkgs; [\n    git\n  ];\n}\n'
HOME_WPKGS = '{ pkgs, ... }:\n{\n  home.packages = with pkgs; [\n    git\n  ];\n}\n'
SYS_EXPL = '{ pkgs, ... }:\n{\n  environment.systemPackages = [\n    pkgs.git\n  ];\n}\n'
HOME_EXPL = '{ pkgs, ... }:\n{\n  home.packages = [\n    pkgs.git\n  ];\n}\n'

MULTILINE = '''{ pkgs, ... }:
{
  home.packages =
    with pkgs; [
      git
      vim
    ];
}
'''
SYS_MULTILINE = MULTILINE.replace("home.packages", "environment.systemPackages")

CROSS = '''{ pkgs, ... }:
{
  home.packages = [
    pkgs.git
  ];
  environment.systemPackages = with pkgs; [
    vim
  ];
}
'''

FLAKE_NIX = '{\n  inputs = {\n    nixpkgs.url = "github:NixOS/nixpkgs";\n  };\n  outputs = { nixpkgs, ... }: {\n  };\n}\n'

FLAKE_LINE = "inputs.repo.packages.${pkgs.stdenv.hostPlatform.system}.default"


# ══════════════════════════════════════════════════════════════════════════
# [1] detect_format — full matrix, both blocks
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("content,block,expected", [
    (SYS_WPKGS, SYSTEM, "with_pkgs"),
    (HOME_WPKGS, HOME, "with_pkgs"),
    (SYS_EXPL, SYSTEM, "explicit_pkgs"),
    (HOME_EXPL, HOME, "explicit_pkgs"),
    (MULTILINE, HOME, "with_pkgs"),
    (SYS_MULTILINE, SYSTEM, "with_pkgs"),
    ('{\n  home.packages = [ ];\n}', HOME, "empty"),
    ('{\n  home.packages = [];\n}', HOME, "empty"),
    ('{\n  home.packages = with pkgs; [ ];\n}', HOME, "empty"),
    ('{\n  home.packages = [\n\n  ];\n}', HOME, "empty"),
    ('{\n  home.username = "u";\n}', HOME, "missing"),
    ("", HOME, "missing"),
    ('{ pkgs, ... }:\n{\n  # home.packages is managed manually\n  home.username = "u";\n}', HOME, "missing"),
    ('{\n  environment.systemPackages = import ./pkgs.nix;\n}', SYSTEM, "external"),
    ('{\n  environment.systemPackages = import ../sub/pkgs.nix;\n}', SYSTEM, "external"),
    ('{\n  environment.systemPackages = mkMerge [ git ];\n}', SYSTEM, "unknown"),
    ('{\n  environment.systemPackages = lib.mkIf true [ git ];\n}', SYSTEM, "unknown"),
    ('{\n  environment.systemPackages = [ git ] ++ [ vim ];\n}', SYSTEM, "unknown"),
    ('{\n  environment.systemPackages = [\n    git\n  ];\n}', SYSTEM, "unknown"),
    ('{\n  environment.systemPackages = with pkgs; [\n    git\n}', SYSTEM, "unknown"),
    (CROSS, HOME, "explicit_pkgs"),
    (CROSS.replace("  home.packages = [\n    pkgs.git\n  ];\n",
                   "  environment.systemPackages = [\n    pkgs.vim\n  ];\n")
        .replace("  environment.systemPackages = with pkgs; [\n    vim\n  ];\n",
                 "  home.packages = with pkgs; [\n    git\n  ];\n"), SYSTEM, "explicit_pkgs"),
    ('{\n  home.packages = [\n    git\n  ];\n  programs.vim.package = pkgs.vim;\n}', HOME, "unknown"),
], ids=[
    "system with_pkgs",
    "home with_pkgs",
    "system explicit",
    "home explicit",
    "multiline with pkgs (different line) → with_pkgs",
    "multiline system with pkgs → with_pkgs",
    "empty [ ] → empty",
    "empty [] → empty",
    "empty with-pkgs form → empty",
    "empty newline inside → empty",
    "missing block → missing",
    "empty file → missing",
    "comment-only mention → missing",
    "import ./ → external",
    "import ../ → external",
    "mkMerge → unknown",
    "lib.mkIf → unknown",
    "concat [a] ++ [b] → unknown",
    "bare names without pkgs. → unknown",
    "unclosed bracket → unknown",
    "REGRESSION: plain home + with-pkgs system → home is explicit_pkgs",
    "REGRESSION: plain system + with-pkgs home → system is explicit_pkgs",
    "pkgs. elsewhere in file does not make bare list explicit",
])
def test_detect_format_matrix(content, block, expected):
    assert detect_format(content, block) == expected


# ══════════════════════════════════════════════════════════════════════════
# [1b] detect_format scoping
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("content,block,expected", [
    ('{ pkgs, ... }: { home.packages = with pkgs; [ git vim ]; }', HOME, "with_pkgs"),
    ('{ pkgs, ... }: { home.packages = with    pkgs ; [ git ]; }', HOME, "with_pkgs"),
    ('{ pkgs, ... }: { home.packages = # hi\n  with pkgs; [ git ]; }', HOME, "with_pkgs"),
    ('{ pkgs, ... }: { home.packages = [ pkgs.git pkgs.vim ]; }', HOME, "explicit_pkgs"),
    ('{ pkgs, ... }: { home.packages = [ pkgs.git # c\n ]; }', HOME, "explicit_pkgs"),
    ('{ pkgs, ... }: { home.packages = [ (pkgs.foo.override { x = "]"; }) ]; }', HOME, "explicit_pkgs"),
    ('{ pkgs, ... }: { home.packages = [ ]; }', HOME, "empty"),
    ('{ pkgs, ... }: { home.username = "u"; }', HOME, "missing"),
    ('{ pkgs, ... }: { environment.systemPackages = import ./p.nix; }', SYSTEM, "external"),
    ('{ pkgs, ... }: { home.packages = mkMerge [ git ]; }', HOME, "unknown"),
    ('{ pkgs, ... }: { home.packages = lib.mkIf x [ git ]; }', HOME, "unknown"),
    ('{ pkgs, ... }: { home.packages = [ a ] ++ [ b ]; }', HOME, "unknown"),
    ('{ pkgs, ... }: { home.packages =\n  other.option = [ pkgs.foo ]; }', HOME, "unknown"),
    ('{ pkgs, ... }: { home.packages = with pkgs; [ git # see ]\n ]; }', HOME, "with_pkgs"),
    ('{ pkgs, ... }: { home.packages = something; }', HOME, "unknown"),
    ('{ pkgs, ... }: { home.packages =', HOME, "unknown"),
    ('{ pkgs, ... }: { # home.packages here\n  foo.bar = [ pkgs.x ]; }', HOME, "missing"),
    ('{ pkgs, ... }: { bar = "home.packages"; foo = [ pkgs.x ]; }', HOME, "missing"),
], ids=[
    "with_pkgs one-line",
    "with_pkgs extra spaces around pkgs;",
    "with_pkgs with trailing before",
    "explicit one-line",
    "explicit with inline comment",
    "explicit ] inside quoted string",
    "empty list",
    "missing block",
    "external import",
    "mkMerge → unknown",
    "lib.mkIf → unknown",
    "[ a ] ++ [ b ] → unknown",
    "assignment after = → unknown",
    "[ inside line comment → with_pkgs (skipped)",
    "bare identifier value → unknown",
    "malformed = at EOF → unknown",
    "block name in comment only → missing",
    "block name in string only → missing",
])
def test_detect_format_scoping(content, block, expected):
    assert detect_format(content, block) == expected


# ══════════════════════════════════════════════════════════════════════════
# [2] add_package — contract per format
# ══════════════════════════════════════════════════════════════════════════

def test_add_package_supported_formats():
    r = add_package(SYS_WPKGS, "htop", Path("/tmp"))
    assert r.status == "success" and "htop" in r.content
    r = add_package(SYS_EXPL, "htop", Path("/tmp"))
    assert r.status == "success" and "pkgs.htop" in r.content
    r = add_package(MULTILINE, "htop", Path("/tmp"), HOME)
    assert r.status == "success" and "htop" in r.content


@pytest.mark.parametrize("label,content,block,status", [
    ("empty", '{ pkgs, ... }:\n{\n  home.packages = [ ];\n}\n', HOME, "unsupported_empty"),
    ("missing", '{ pkgs, ... }:\n{\n  home.username = "u";\n}\n', HOME, "unsupported_missing"),
    ("external", '{ pkgs, ... }:\n{\n  environment.systemPackages = import ./pkgs.nix;\n}\n',
     SYSTEM, "unsupported_external"),
    ("unknown-mkMerge", '{ pkgs, ... }:\n{\n  environment.systemPackages = mkMerge [ git ];\n}\n',
     SYSTEM, "unsupported_unknown"),
    ("unknown-bare", '{ pkgs, ... }:\n{\n  environment.systemPackages = [\n    git\n  ];\n}\n',
     SYSTEM, "unsupported_unknown"),
], ids=[
    "empty: unsupported_empty + content byte-for-byte unchanged",
    "missing: unsupported_missing + content byte-for-byte unchanged",
    "external: unsupported_external + content byte-for-byte unchanged",
    "unknown-mkMerge: unsupported_unknown + content byte-for-byte unchanged",
    "unknown-bare: unsupported_unknown + content byte-for-byte unchanged",
])
def test_add_package_unsupported_formats(label, content, block, status):
    r = add_package(content, "htop", Path("/tmp"), block)
    assert r.status == status, f"status={r.status}"
    assert r.content == content


def test_add_package_no_change_when_handler_returns_identical():
    with patch("core.writer.add_package_with_pkgs", side_effect=lambda c, p, b: c):
        r = add_package(SYS_WPKGS, "htop", Path("/tmp"))
    assert r.status == "no_change"
    assert r.content == SYS_WPKGS


def test_add_package_error_when_handler_raises():
    with patch("core.writer.add_package_with_pkgs", side_effect=RuntimeError("boom")):
        r = add_package(SYS_WPKGS, "htop", Path("/tmp"))
    assert r.status == "error"
    assert r.content == SYS_WPKGS


# ══════════════════════════════════════════════════════════════════════════
# [3] pkgs. prefix normalization (no double prefix)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("ref,expected", [
    ("vim", "pkgs.vim"),
    ("pkgs.vim", "pkgs.vim"),
    ("unstable.vim", "unstable.vim"),
    ("inputs.foo.packages.${pkgs.stdenv.hostPlatform.system}.vim",
     "inputs.foo.packages.${pkgs.stdenv.hostPlatform.system}.vim"),
], ids=[
    "vim → pkgs.vim",
    "pkgs.vim → pkgs.vim",
    "unstable.vim → unstable.vim",
    "inputs.foo... → inputs.foo...",
])
def test_add_package_explicit_reference_normalization(ref, expected):
    r = add_package(SYS_EXPL, ref, Path("/tmp"))
    added = [l.strip() for l in r.content.split("\n")
             if expected in l and "pkgs.git" not in l]
    assert r.status == "success"
    assert bool(added)


# ══════════════════════════════════════════════════════════════════════════
# [4] remove_package / is_package_exists — gate behavior
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("label,content,block", [
    ("empty", '{\n  home.packages = [ ];\n}', HOME),
    ("missing", '{\n  home.username = "u";\n}', HOME),
    ("external", '{\n  environment.systemPackages = import ./p.nix;\n}', SYSTEM),
    ("unknown", '{\n  environment.systemPackages = mkMerge [ git ];\n}', SYSTEM),
], ids=["empty", "missing", "external", "unknown"])
def test_remove_and_exists_gate_unsupported(label, content, block):
    out, found = remove_package(content, "git", Path("/tmp"), block)
    assert out == content
    assert found is False
    assert is_package_exists(content, "git", Path("/tmp"), block) is False


def test_remove_package_supported():
    out, found = remove_package(SYS_WPKGS, "git", Path("/tmp"))
    assert found and "git" not in out
    assert is_package_exists(SYS_WPKGS, "git", Path("/tmp"))
    out, found = remove_package(SYS_EXPL, "git", Path("/tmp"))
    assert found and "pkgs.git" not in out
    assert is_package_exists(SYS_EXPL, "git", Path("/tmp"))


# ══════════════════════════════════════════════════════════════════════════
# [5] add_flake_package — no bypass, fallback only on missing
# ══════════════════════════════════════════════════════════════════════════

def test_add_flake_package_contract():
    r = add_flake_package(HOME_EXPL, "repo", "default", block=HOME)
    line = [l for l in r.content.split("\n") if "inputs.repo" in l]
    assert r.status == "success"
    assert line and line[0].strip() == FLAKE_LINE

    r = add_flake_package(HOME_WPKGS, "repo", "default", block=HOME)
    assert r.status == "success" and "inputs.repo.packages" in r.content

    r = add_flake_package('{\n  home.packages = [ ];\n}', "repo", "default", block=HOME)
    assert r.status == "unsupported_empty"

    r = add_flake_package('{\n  home.packages = [ ];\n  environment.systemPackages = with pkgs; [ git ];\n}',
                          "repo", "default")
    assert r.status == "unsupported_empty"

    r = add_flake_package(SYS_WPKGS, "repo", "default")
    assert r.status == "success" and "inputs.repo.packages" in r.content

    r = add_flake_package(HOME_WPKGS + '\n  environment.systemPackages = with pkgs; [ vim ];\n'
                          .join(["{ pkgs, ... }:\n{\n", "}"]), "repo", "default")
    assert r.status == "success" and "inputs.repo.packages" in r.content


# ══════════════════════════════════════════════════════════════════════════
# [6] add_flake — 3-tuple with status
# ══════════════════════════════════════════════════════════════════════════

def test_add_flake_status_propagation():
    fc, hc, st = add_flake(FLAKE_NIX, "repo", "github:x/y", "default", "package",
                           home_content=HOME_WPKGS, block=HOME)
    assert st == "success" and "inputs.repo.packages" in hc

    fc, hc, st = add_flake(FLAKE_NIX, "repo", "github:x/y", "default", "package",
                           home_content='{\n  home.packages = [ ];\n}', block=HOME)
    assert st == "unsupported_empty"
    assert hc == '{\n  home.packages = [ ];\n}'

    fc, hc, st = add_flake(FLAKE_NIX, "repo", "github:x/y", "default", "nixosModule")
    assert st == "success"


# ══════════════════════════════════════════════════════════════════════════
# [7] executor — unsupported format → False, no rebuild, restore called
# ══════════════════════════════════════════════════════════════════════════

def _make_plan():
    from flakes.models import FlakeSource, FlakeOutput, InstallationPlan
    return InstallationPlan(
        source=FlakeSource(url="github:x/y"),
        output=FlakeOutput(name="default", type="packages",
                           attribute="packages.x86_64-linux.default"),
        action="install", system="x86_64-linux", flake_name="repo",
    )


def test_executor_unsupported_format_gate(tmp_path):
    from flakes.executor import execute

    (tmp_path / "flake.nix").write_text(FLAKE_NIX)
    (tmp_path / "home.nix").write_text('{\n  home.packages = [ ];\n}')
    (tmp_path / "configuration.nix").write_text(SYS_WPKGS)
    cfg = {"setup": {"configuration_path": str(tmp_path / "configuration.nix"),
                     "flake_enabled": True, "flake_path": str(tmp_path / "flake.nix"),
                     "home_manager_enabled": True,
                     "home_manager_path": str(tmp_path / "home.nix")}}
    with patch("flakes.executor.subprocess.run") as mr, \
         patch("flakes.executor.backup_files") as mb, \
         patch("flakes.executor.restore_files") as mrb:
        mr.return_value = MagicMock(returncode=0)
        ok = execute([_make_plan()], cfg, target=Target.HOME)
    assert ok is False
    assert not mr.called
    assert mrb.called
    assert (tmp_path / "home.nix").read_text() == '{\n  home.packages = [ ];\n}'


# ══════════════════════════════════════════════════════════════════════════
# [8] main/UI boundary — pre-check shows message, execute not called
# ══════════════════════════════════════════════════════════════════════════

def test_main_flakes_install_unsupported_format(tmp_path):
    import main as main_mod

    (tmp_path / "flake.nix").write_text(FLAKE_NIX)
    (tmp_path / "home.nix").write_text('{\n  home.packages = [ ];\n}')
    cfg = {"setup": {"configuration_path": str(tmp_path / "configuration.nix"),
                     "flake_enabled": True, "flake_path": str(tmp_path / "flake.nix"),
                     "home_manager_enabled": True,
                     "home_manager_path": str(tmp_path / "home.nix")}}
    with patch("main.parse_flake_url") as mp, \
         patch("main.show_unsupported_format") as ms, \
         redirect_stdout(io.StringIO()):
        main_mod.handle_flakes_install("github:x/y", cfg, requested=Target.HOME)
    assert ms.called
    assert not mp.called


def test_main_remove_unsupported_format(tmp_path):
    import main as main_mod

    conf = tmp_path / "configuration.nix"
    conf.write_text('{\n  environment.systemPackages = import ./pkgs.nix;\n}')
    cfg = {"setup": {"configuration_path": str(conf), "flake_enabled": False}}
    with patch("main.show_unsupported_format") as ms, \
         patch("main.is_package_exists") as mie, \
         redirect_stdout(io.StringIO()):
        main_mod.handle_remove("git", cfg)
    assert ms.called
    assert not mie.called


# ══════════════════════════════════════════════════════════════════════════
# [9] Detection boundaries — strengthened detector
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("content,expected", [
    ('{ pkgs, ... }:\n{\n  home.packages =\n\n  other.option = [\n    pkgs.foo\n  ];\n}\n',
     "unknown"),
    ('{ pkgs, ... }:\n{\n  home.packages =\n  other.option = [\n    pkgs.git\n  ];\n}\n',
     "unknown"),
    ('{ pkgs, ... }:\n{\n  home.packages =\n    # managed\n    [ pkgs.git ];\n}\n',
     "explicit_pkgs"),
    ('{ pkgs, ... }:\n{\n  home.packages =\n    # list\n    with pkgs; [ git ];\n}\n',
     "with_pkgs"),
    ('{ pkgs, ... }:\n{\n  home.packages =  # note ]\n    with pkgs; [ git ];\n}\n',
     "with_pkgs"),
    ('{ pkgs, ... }:\n{\n  home.packages = with pkgs; [\n    git\n    # see [docs] ]\n  ];\n}\n',
     "with_pkgs"),
    ('{ pkgs, ... }:\n{\n  home.packages = with pkgs; [\n    (pkgs.foo.override { x = "]"; })\n  ];\n}\n',
     "with_pkgs"),
    ('{ pkgs, ... }:\n{\n  home.packages =\n    # todo\n}\n', "unknown"),
    ('{\n  home.packages =', "unknown"),
    ('{\n  home.packages = something;\n}', "unknown"),
], ids=[
    "assignment after = (blank line) → unknown",
    "assignment after = (no blank) → unknown",
    "comment line before list → explicit_pkgs",
    "comment line before with pkgs → with_pkgs",
    "trailing comment with ] before value → with_pkgs",
    "] inside line comment inside list → with_pkgs",
    "] inside quoted string inside list → with_pkgs",
    "= with only a comment afterwards → unknown",
    "= at end of file → unknown",
    "value is a bare identifier → unknown",
])
def test_detect_format_boundaries(content, expected):
    assert detect_format(content, HOME) == expected


# ══════════════════════════════════════════════════════════════════════════
# [10] Mutation gateway — architectural invariant
# ══════════════════════════════════════════════════════════════════════════

def test_add_flake_package_routes_through_add_package():
    with patch("core.writer.add_package",
               side_effect=lambda c, p, d, b="environment.systemPackages":
               AddResult(content=c, status="unsupported_unknown")) as mock_add:
        r1 = add_flake_package(HOME_WPKGS, "repo", "default", block=HOME)
        r2 = add_flake_package(SYS_WPKGS, "repo", "default")
    assert mock_add.called
    assert r1.status == "unsupported_unknown"
    assert mock_add.call_count == 2
    assert r2.status == "unsupported_unknown"


@pytest.mark.parametrize("label,content,block", [
    ("empty", '{\n  home.packages = [ ];\n}', HOME),
    ("missing", '{\n  home.username = "u";\n}', HOME),
    ("external", '{\n  environment.systemPackages = import ./p.nix;\n}', SYSTEM),
    ("unknown", '{\n  environment.systemPackages = mkMerge [ git ];\n}', SYSTEM),
], ids=["empty", "missing", "external", "unknown"])
def test_add_package_never_mutates_unsupported(label, content, block):
    r = add_package(content, "htop", Path("/tmp"), block)
    assert r.content == content


def test_supported_handlers_called_only_inside_add_package():
    import core.writer as _w
    wlines = inspect.getsource(_w).split("\n")
    wdef = [i for i, l in enumerate(wlines) if l.startswith("def add_package(")][0]
    wend = next(i for i in range(wdef + 1, len(wlines))
                if wlines[i] and not wlines[i][0].isspace())
    outside_calls = [
        f"line {i + 1}: {l.strip()}"
        for i, l in enumerate(wlines)
        for h in ("add_package_with_pkgs", "add_package_explicit_pkgs")
        if f"{h}(" in l and f"def {h}(" not in l and not (wdef <= i <= wend)
    ]
    assert not outside_calls, "; ".join(outside_calls)
