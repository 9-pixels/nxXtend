"""Writer format contract tests (Beta).

Covers the full chain: detect_format → SUPPORTED_FORMATS gate →
add_package result → add_flake_package → executor → main/UI boundary.

Beta contract: only `with_pkgs` and `explicit_pkgs` may be modified.
empty / missing / external / unknown are detected but never mutated.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, "/home/ayman/Projects/nix-install")

from src.core.writer import (
    SUPPORTED_FORMATS, detect_format, add_package, remove_package,
    is_package_exists, add_flake_package, add_flake, AddResult,
)

SYSTEM = "environment.systemPackages"
HOME = "home.packages"
PASS, FAIL = [], []


def check(label, ok, detail=""):
    (PASS if ok else FAIL).append(label)
    print(f"  {'✓' if ok else '✗'} {label}" + (f"  [{detail}]" if not ok and detail else ""))


# ══════════════════════════════════════════════════════════════════════════
# [1] detect_format — full matrix, both blocks
# ══════════════════════════════════════════════════════════════════════════
print("\n[1] detect_format matrix")

SYS_WPKGS = '{ pkgs, ... }:\n{\n  environment.systemPackages = with pkgs; [\n    git\n  ];\n}\n'
HOME_WPKGS = '{ pkgs, ... }:\n{\n  home.packages = with pkgs; [\n    git\n  ];\n}\n'
SYS_EXPL = '{ pkgs, ... }:\n{\n  environment.systemPackages = [\n    pkgs.git\n  ];\n}\n'
HOME_EXPL = '{ pkgs, ... }:\n{\n  home.packages = [\n    pkgs.git\n  ];\n}\n'

check("system with_pkgs", detect_format(SYS_WPKGS) == "with_pkgs")
check("home with_pkgs", detect_format(HOME_WPKGS, HOME) == "with_pkgs")
check("system explicit", detect_format(SYS_EXPL) == "explicit_pkgs")
check("home explicit", detect_format(HOME_EXPL, HOME) == "explicit_pkgs")

# multiline `= \n with pkgs; [` — the two required spellings
MULTILINE = '''{ pkgs, ... }:
{
  home.packages =
    with pkgs; [
      git
      vim
    ];
}
'''
check("multiline with pkgs (different line) → with_pkgs",
      detect_format(MULTILINE, HOME) == "with_pkgs")
SYS_MULTILINE = MULTILINE.replace("home.packages", "environment.systemPackages")
check("multiline system with pkgs → with_pkgs",
      detect_format(SYS_MULTILINE) == "with_pkgs")

# empty — both spellings, both blocks
check("empty [ ] → empty", detect_format('{\n  home.packages = [ ];\n}', HOME) == "empty")
check("empty [] → empty", detect_format('{\n  home.packages = [];\n}', HOME) == "empty")
check("empty with-pkgs form → empty",
      detect_format('{\n  home.packages = with pkgs; [ ];\n}', HOME) == "empty")
check("empty newline inside → empty",
      detect_format('{\n  home.packages = [\n\n  ];\n}', HOME) == "empty")

# missing
check("missing block → missing", detect_format('{\n  home.username = "u";\n}', HOME) == "missing")
check("empty file → missing", detect_format("", HOME) == "missing")
check("comment-only mention → missing",
      detect_format('{ pkgs, ... }:\n{\n  # home.packages is managed manually\n  home.username = "u";\n}', HOME) == "missing")

# external — both spellings
check("import ./ → external",
      detect_format('{\n  environment.systemPackages = import ./pkgs.nix;\n}') == "external")
check("import ../ → external",
      detect_format('{\n  environment.systemPackages = import ../sub/pkgs.nix;\n}') == "external")

# unknown — non-list values and bare-name lists
check("mkMerge → unknown",
      detect_format('{\n  environment.systemPackages = mkMerge [ git ];\n}') == "unknown")
check("lib.mkIf → unknown",
      detect_format('{\n  environment.systemPackages = lib.mkIf true [ git ];\n}') == "unknown")
check("concat [a] ++ [b] → unknown",
      detect_format('{\n  environment.systemPackages = [ git ] ++ [ vim ];\n}') == "unknown")
check("bare names without pkgs. → unknown",
      detect_format('{\n  environment.systemPackages = [\n    git\n  ];\n}') == "unknown")
check("unclosed bracket → unknown",
      detect_format('{\n  environment.systemPackages = with pkgs; [\n    git\n}') == "unknown")

# THE regression: cross-block with pkgs must not leak
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
check("REGRESSION: plain home + with-pkgs system → home is explicit_pkgs",
      detect_format(CROSS, HOME) == "explicit_pkgs")
check("REGRESSION: plain system + with-pkgs home → system is explicit_pkgs",
      detect_format(CROSS.replace("  home.packages = [\n    pkgs.git\n  ];\n", "  environment.systemPackages = [\n    pkgs.vim\n  ];\n").replace("  environment.systemPackages = with pkgs; [\n    vim\n  ];\n", "  home.packages = with pkgs; [\n    git\n  ];\n")) == "explicit_pkgs")
check("pkgs. elsewhere in file does not make bare list explicit",
      detect_format('{\n  home.packages = [\n    git\n  ];\n  programs.vim.package = pkgs.vim;\n}', HOME) == "unknown")

# ══════════════════════════════════════════════════════════════════════════
# [1b] detect_format scoping — permanent regression tests (audit §2)
#    Compressed Nix, inline comments, strings, block-name-in-comment/string
#    traps. Prevents future regex relaxation from reintroducing false positives.
# ══════════════════════════════════════════════════════════════════════════
print("\n[1b] detect_format scoping (audit §2)")

check("with_pkgs one-line",
      detect_format('{ pkgs, ... }: { home.packages = with pkgs; [ git vim ]; }', HOME) == "with_pkgs")
check("with_pkgs extra spaces around pkgs;",
      detect_format('{ pkgs, ... }: { home.packages = with    pkgs ; [ git ]; }', HOME) == "with_pkgs")
check("with_pkgs with trailing before",
      detect_format('{ pkgs, ... }: { home.packages = # hi\n  with pkgs; [ git ]; }', HOME) == "with_pkgs")
check("explicit one-line",
      detect_format('{ pkgs, ... }: { home.packages = [ pkgs.git pkgs.vim ]; }', HOME) == "explicit_pkgs")
check("explicit with inline comment",
      detect_format('{ pkgs, ... }: { home.packages = [ pkgs.git # c\n ]; }', HOME) == "explicit_pkgs")
check("explicit ] inside quoted string",
      detect_format('{ pkgs, ... }: { home.packages = [ (pkgs.foo.override { x = "]"; }) ]; }', HOME) == "explicit_pkgs")
check("empty list",
      detect_format('{ pkgs, ... }: { home.packages = [ ]; }', HOME) == "empty")
check("missing block",
      detect_format('{ pkgs, ... }: { home.username = "u"; }', HOME) == "missing")
check("external import",
      detect_format('{ pkgs, ... }: { environment.systemPackages = import ./p.nix; }', SYSTEM) == "external")
check("mkMerge → unknown",
      detect_format('{ pkgs, ... }: { home.packages = mkMerge [ git ]; }', HOME) == "unknown")
check("lib.mkIf → unknown",
      detect_format('{ pkgs, ... }: { home.packages = lib.mkIf x [ git ]; }', HOME) == "unknown")
check("[ a ] ++ [ b ] → unknown",
      detect_format('{ pkgs, ... }: { home.packages = [ a ] ++ [ b ]; }', HOME) == "unknown")
check("assignment after = → unknown",
      detect_format('{ pkgs, ... }: { home.packages =\n  other.option = [ pkgs.foo ]; }', HOME) == "unknown")
check("[ inside line comment → with_pkgs (skipped)",
      detect_format('{ pkgs, ... }: { home.packages = with pkgs; [ git # see ]\n ]; }', HOME) == "with_pkgs")
check("bare identifier value → unknown",
      detect_format('{ pkgs, ... }: { home.packages = something; }', HOME) == "unknown")
check("malformed = at EOF → unknown",
      detect_format('{ pkgs, ... }: { home.packages =', HOME) == "unknown")
check("block name in comment only → missing",
      detect_format('{ pkgs, ... }: { # home.packages here\n  foo.bar = [ pkgs.x ]; }', HOME) == "missing")
check("block name in string only → missing",
      detect_format('{ pkgs, ... }: { bar = "home.packages"; foo = [ pkgs.x ]; }', HOME) == "missing")


# ══════════════════════════════════════════════════════════════════════════
# [2] add_package — contract per format
# ══════════════════════════════════════════════════════════════════════════
print("\n[2] add_package contract")

# supported → success + content changed
r = add_package(SYS_WPKGS, "htop", Path("/tmp"))
check("with_pkgs: success + htop added", r.status == "success" and "htop" in r.content)
r = add_package(SYS_EXPL, "htop", Path("/tmp"))
check("explicit: success + pkgs.htop added", r.status == "success" and "pkgs.htop" in r.content)
r = add_package(MULTILINE, "htop", Path("/tmp"), HOME)
check("multiline with_pkgs: success + htop added", r.status == "success" and "htop" in r.content)

# unsupported → status + byte-for-byte unchanged
for label, content, block, status in [
    ("empty", '{ pkgs, ... }:\n{\n  home.packages = [ ];\n}\n', HOME, "unsupported_empty"),
    ("missing", '{ pkgs, ... }:\n{\n  home.username = "u";\n}\n', HOME, "unsupported_missing"),
    ("external", '{ pkgs, ... }:\n{\n  environment.systemPackages = import ./pkgs.nix;\n}\n', SYSTEM, "unsupported_external"),
    ("unknown-mkMerge", '{ pkgs, ... }:\n{\n  environment.systemPackages = mkMerge [ git ];\n}\n', SYSTEM, "unsupported_unknown"),
    ("unknown-bare", '{ pkgs, ... }:\n{\n  environment.systemPackages = [\n    git\n  ];\n}\n', SYSTEM, "unsupported_unknown"),
]:
    r = add_package(content, "htop", Path("/tmp"), block)
    check(f"{label}: {status} + content byte-for-byte unchanged",
          r.status == status and r.content == content,
          f"status={r.status}")

# no_change — defensive: handler returns identical content
original = add_package(SYS_WPKGS, "htop", Path("/tmp")).content
with patch("src.core.writer.add_package_with_pkgs", side_effect=lambda c, p, b: c):
    r = add_package(SYS_WPKGS, "htop", Path("/tmp"))
check("no_change when supported handler returns identical content",
      r.status == "no_change" and r.content == SYS_WPKGS)

# error — handler raises
with patch("src.core.writer.add_package_with_pkgs", side_effect=RuntimeError("boom")):
    r = add_package(SYS_WPKGS, "htop", Path("/tmp"))
check("error when handler raises (original content preserved)",
      r.status == "error" and r.content == SYS_WPKGS)


# ══════════════════════════════════════════════════════════════════════════
# [3] pkgs. prefix normalization (no double prefix)
# ══════════════════════════════════════════════════════════════════════════
print("\n[3] explicit reference normalization")

for ref, expected in [
    ("vim", "pkgs.vim"),
    ("pkgs.vim", "pkgs.vim"),
    ("unstable.vim", "unstable.vim"),
    ("inputs.foo.packages.${pkgs.stdenv.hostPlatform.system}.vim",
     "inputs.foo.packages.${pkgs.stdenv.hostPlatform.system}.vim"),
]:
    r = add_package(SYS_EXPL, ref, Path("/tmp"))
    added = [l.strip() for l in r.content.split("\n") if expected in l and "pkgs.git" not in l]
    check(f"{ref} → {expected}", r.status == "success" and bool(added),
          f"status={r.status} added={added}")


# ══════════════════════════════════════════════════════════════════════════
# [4] remove_package / is_package_exists — gate behavior
# ══════════════════════════════════════════════════════════════════════════
print("\n[4] remove/exists gate")

for label, content, block in [
    ("empty", '{\n  home.packages = [ ];\n}', HOME),
    ("missing", '{\n  home.username = "u";\n}', HOME),
    ("external", '{\n  environment.systemPackages = import ./p.nix;\n}', SYSTEM),
    ("unknown", '{\n  environment.systemPackages = mkMerge [ git ];\n}', SYSTEM),
]:
    out, found = remove_package(content, "git", Path("/tmp"), block)
    check(f"{label}: remove → (unchanged, False)",
          out == content and found is False)
    check(f"{label}: exists → False",
          is_package_exists(content, "git", Path("/tmp"), block) is False)

# supported: no regression
out, found = remove_package(SYS_WPKGS, "git", Path("/tmp"))
check("with_pkgs remove: found, git gone", found and "git" not in out)
check("with_pkgs exists", is_package_exists(SYS_WPKGS, "git", Path("/tmp")))
out, found = remove_package(SYS_EXPL, "git", Path("/tmp"))
check("explicit remove (bare name matches pkgs.git)", found and "pkgs.git" not in out)
check("explicit exists (bare name)", is_package_exists(SYS_EXPL, "git", Path("/tmp")))


# ══════════════════════════════════════════════════════════════════════════
# [5] add_flake_package — no bypass, fallback only on missing
# ══════════════════════════════════════════════════════════════════════════
print("\n[5] add_flake_package contract")

FLAKE_LINE = "inputs.repo.packages.${pkgs.stdenv.hostPlatform.system}.default"

# explicit block, supported → success, no pkgs. prefix on flake ref
r = add_flake_package(HOME_EXPL, "repo", "default", block=HOME)
line = [l for l in r.content.split("\n") if "inputs.repo" in l]
check("flake ref in explicit home: no pkgs. prefix (full-line)",
      r.status == "success" and line and line[0].strip() == FLAKE_LINE,
      f"line={line}")

r = add_flake_package(HOME_WPKGS, "repo", "default", block=HOME)
check("flake ref in with_pkgs home: success", r.status == "success" and "inputs.repo.packages" in r.content)

# unsupported home (empty) + explicit block → unsupported_empty, NO fallback
r = add_flake_package('{\n  home.packages = [ ];\n}', "repo", "default", block=HOME)
check("empty home + explicit block → unsupported_empty (no fallback)",
      r.status == "unsupported_empty")

# block=None: home exists but unsupported → status preserved, NO silent fallback
r = add_flake_package('{\n  home.packages = [ ];\n  environment.systemPackages = with pkgs; [ git ];\n}',
                      "repo", "default")
check("block=None: unsupported home keeps status (no silent System fallback)",
      r.status == "unsupported_empty")

# block=None: home missing → legacy fallback to SYSTEM
r = add_flake_package(SYS_WPKGS, "repo", "default")
check("block=None: missing home → System fallback works",
      r.status == "success" and "inputs.repo.packages" in r.content)

# block=None: home supported → home targeted
r = add_flake_package(HOME_WPKGS + '\n  environment.systemPackages = with pkgs; [ vim ];\n'.join(["{ pkgs, ... }:\n{", "}"]),
                      "repo", "default")
check("block=None: supported home is targeted first",
      r.status == "success" and "inputs.repo.packages" in r.content)


# ══════════════════════════════════════════════════════════════════════════
# [6] add_flake — 3-tuple with status
# ══════════════════════════════════════════════════════════════════════════
print("\n[6] add_flake status propagation")

FLAKE_NIX = '{\n  inputs = {\n    nixpkgs.url = "github:NixOS/nixpkgs";\n  };\n  outputs = { nixpkgs, ... }: {\n  };\n}\n'

fc, hc, st = add_flake(FLAKE_NIX, "repo", "github:x/y", "default", "package",
                       home_content=HOME_WPKGS, block=HOME)
check("supported home: status success, ref in home",
      st == "success" and "inputs.repo.packages" in hc)

fc, hc, st = add_flake(FLAKE_NIX, "repo", "github:x/y", "default", "package",
                       home_content='{\n  home.packages = [ ];\n}', block=HOME)
check("unsupported home: status propagated (not swallowed)",
      st == "unsupported_empty" and hc == '{\n  home.packages = [ ];\n}')

fc, hc, st = add_flake(FLAKE_NIX, "repo", "github:x/y", "default", "nixosModule")
check("nixosModule: status stays success",
      st == "success")


# ══════════════════════════════════════════════════════════════════════════
# [7] executor — unsupported format → False, no rebuild, restore called
# ══════════════════════════════════════════════════════════════════════════
print("\n[7] executor gate")

from src.flakes.executor import execute
from src.flakes.models import FlakeSource, FlakeOutput, InstallationPlan
from src.core.target import Target

def make_plan():
    return InstallationPlan(
        source=FlakeSource(url="github:x/y"),
        output=FlakeOutput(name="default", type="packages", attribute="packages.x86_64-linux.default"),
        action="install", system="x86_64-linux", flake_name="repo",
    )

with tempfile.TemporaryDirectory() as td:
    Path(td, "flake.nix").write_text(FLAKE_NIX)
    Path(td, "home.nix").write_text('{\n  home.packages = [ ];\n}')  # unsupported
    Path(td, "configuration.nix").write_text(SYS_WPKGS)
    cfg = {"setup": {"configuration_path": str(Path(td, "configuration.nix")),
                     "flake_enabled": True, "flake_path": str(Path(td, "flake.nix")),
                     "home_manager_enabled": True, "home_manager_path": str(Path(td, "home.nix"))}}
    with patch("src.flakes.executor.subprocess.run") as mr, \
         patch("src.flakes.executor.backup_files") as mb, \
         patch("src.flakes.executor.restore_files") as mrb:
        mr.return_value = MagicMock(returncode=0)
        ok = execute(make_plan(), cfg, target=Target.HOME)
    check("executor: unsupported home format → False", ok is False)
    check("executor: no rebuild ran", not mr.called)
    check("executor: restore called (rollback)", mrb.called)
    check("executor: home.nix untouched",
          Path(td, "home.nix").read_text() == '{\n  home.packages = [ ];\n}')


# ══════════════════════════════════════════════════════════════════════════
# [8] main/UI boundary — pre-check shows message, execute not called
# ══════════════════════════════════════════════════════════════════════════
print("\n[8] main boundary")

import io
from contextlib import redirect_stdout
import main as main_mod

with tempfile.TemporaryDirectory() as td:
    Path(td, "flake.nix").write_text(FLAKE_NIX)
    Path(td, "home.nix").write_text('{\n  home.packages = [ ];\n}')  # unsupported
    cfg = {"setup": {"configuration_path": str(Path(td, "configuration.nix")),
                     "flake_enabled": True, "flake_path": str(Path(td, "flake.nix")),
                     "home_manager_enabled": True, "home_manager_path": str(Path(td, "home.nix"))}}
    with patch("main.parse_flake_url") as mp, \
         patch("main.show_unsupported_format") as ms, \
         redirect_stdout(io.StringIO()):
        main_mod.handle_flakes_install("github:x/y", cfg, requested=Target.HOME)
    check("main: pre-check shows unsupported message", ms.called)
    check("main: resolver never started (execute not reached)",
          not mp.called)

# handle_remove: unsupported format → message, not "not found"
with tempfile.TemporaryDirectory() as td:
    conf = Path(td, "configuration.nix")
    conf.write_text('{\n  environment.systemPackages = import ./pkgs.nix;\n}')
    cfg = {"setup": {"configuration_path": str(conf), "flake_enabled": False}}
    with patch("main.show_unsupported_format") as ms, \
         patch("main.is_package_exists") as mie, \
         redirect_stdout(io.StringIO()):
        main_mod.handle_remove("git", cfg)
    check("main remove: unsupported format → message (not 'not found')", ms.called)
    check("main remove: is_package_exists not reached", not mie.called)


# ══════════════════════════════════════════════════════════════════════════
# [9] Detection boundaries — strengthened detector (§2)
# ══════════════════════════════════════════════════════════════════════════
print("\n[9] detection boundary regressions")

# unrelated assignment between = and a later list → unknown (never the block's list)
check("assignment after = (blank line) → unknown",
      detect_format('{ pkgs, ... }:\n{\n  home.packages =\n\n  other.option = [\n    pkgs.foo\n  ];\n}\n', HOME) == "unknown")
check("assignment after = (no blank) → unknown",
      detect_format('{ pkgs, ... }:\n{\n  home.packages =\n  other.option = [\n    pkgs.git\n  ];\n}\n', HOME) == "unknown")

# comments between = and value are harmless whitespace
check("comment line before list → explicit_pkgs",
      detect_format('{ pkgs, ... }:\n{\n  home.packages =\n    # managed\n    [ pkgs.git ];\n}\n', HOME) == "explicit_pkgs")
check("comment line before with pkgs → with_pkgs",
      detect_format('{ pkgs, ... }:\n{\n  home.packages =\n    # list\n    with pkgs; [ git ];\n}\n', HOME) == "with_pkgs")
check("trailing comment with ] before value → with_pkgs",
      detect_format('{ pkgs, ... }:\n{\n  home.packages =  # note ]\n    with pkgs; [ git ];\n}\n', HOME) == "with_pkgs")

# brackets inside strings/comments inside the list must not break matching
check("] inside line comment inside list → with_pkgs",
      detect_format('{ pkgs, ... }:\n{\n  home.packages = with pkgs; [\n    git\n    # see [docs] ]\n  ];\n}\n', HOME) == "with_pkgs")
check("] inside quoted string inside list → with_pkgs",
      detect_format('{ pkgs, ... }:\n{\n  home.packages = with pkgs; [\n    (pkgs.foo.override { x = "]"; })\n  ];\n}\n', HOME) == "with_pkgs")

# malformed/ambiguous → unknown (prefer unknown over guessing)
check("= with only a comment afterwards → unknown",
      detect_format('{ pkgs, ... }:\n{\n  home.packages =\n    # todo\n}\n', HOME) == "unknown")
check("= at end of file → unknown",
      detect_format('{\n  home.packages =', HOME) == "unknown")
check("value is a bare identifier → unknown",
      detect_format('{\n  home.packages = something;\n}', HOME) == "unknown")

# ══════════════════════════════════════════════════════════════════════════
# [10] Mutation gateway — architectural invariant (§1)
# ══════════════════════════════════════════════════════════════════════════
print("\n[10] single mutation gateway")

# Flake insertion cannot bypass add_package: patch add_package and prove
# add_flake_package routes through it (both explicit-block and fallback).
with patch("src.core.writer.add_package",
           side_effect=lambda c, p, d, b="environment.systemPackages": AddResult(content=c, status="unsupported_unknown")) as mock_add:
    r1 = add_flake_package(HOME_WPKGS, "repo", "default", block=HOME)
    r2 = add_flake_package(SYS_WPKGS, "repo", "default")  # block=None fallback
check("add_flake_package (explicit block) routes through add_package",
      mock_add.called and r1.status == "unsupported_unknown")
check("add_flake_package (fallback) routes through add_package",
      mock_add.call_count == 2 and r2.status == "unsupported_unknown")

# unsupported → no mutation, ever
for label, content, block in [
    ("empty", '{\n  home.packages = [ ];\n}', HOME),
    ("missing", '{\n  home.username = "u";\n}', HOME),
    ("external", '{\n  environment.systemPackages = import ./p.nix;\n}', SYSTEM),
    ("unknown", '{\n  environment.systemPackages = mkMerge [ git ];\n}', SYSTEM),
]:
    r = add_package(content, "htop", Path("/tmp"), block)
    check(f"{label}: content byte-for-byte unchanged", r.content == content)

# the two handlers are module-level but only reachable via add_package's
# dispatch — prove it statically: no call to either handler anywhere in
# production code outside add_package's own body (tests may patch them).
import inspect as _inspect
import src.core.writer as _w
_wlines = _inspect.getsource(_w).split("\n")
_wdef = [i for i, l in enumerate(_wlines) if l.startswith("def add_package(")][0]
_wend = next(i for i in range(_wdef + 1, len(_wlines))
             if _wlines[i] and not _wlines[i][0].isspace())
_outside_calls = [
    f"line {i+1}: {l.strip()}"
    for i, l in enumerate(_wlines)
    for h in ("add_package_with_pkgs", "add_package_explicit_pkgs")
    if f"{h}(" in l and f"def {h}(" not in l and not (_wdef <= i <= _wend)
]
check("handlers called ONLY inside add_package body (single gateway)",
      not _outside_calls, "; ".join(_outside_calls))

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print(f"RESULTS: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    for f in FAIL:
        print(f"  ✗ {f}")
print("=" * 70)
sys.exit(1 if FAIL else 0)
