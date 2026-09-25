"""Beta audit — writer adversarial tests (READ-ONLY audit: asserts CORRECT
behavior; a failed check here documents a bug, not a test error).

Covers: silent no-op paths, format detection, formatting preservation,
duplicates, removal, external imports, malformed input, boundary sizes,
and a formatting-variation property check.
"""
import sys
import os
import time
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from src.core.writer import (
    add_package, remove_package, is_package_exists, detect_format,
    add_package_with_pkgs,
)

SYSTEM = "environment.systemPackages"
HOME = "home.packages"

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f" — {detail}" if not cond else ""))


print("=" * 70)
print("BETA AUDIT 1/3 — WRITER")
print("=" * 70)

# ── [A] Silent no-op paths (critical correctness property) ─────────────────
print("\n[A] add_package must never report success without adding")

# A1: genuinely empty HOME block, nothing else in file
A1 = '{ pkgs, ... }:\n{\n  home.packages = [ ];\n}\n'
r = add_package(A1, "htop", Path("/tmp"), HOME)
check("A1 empty home.packages: success ⇒ htop present",
      r.status != "success" or "htop" in r.content,
      f"status={r.status}, added={'htop' in r.content}")

# A2: genuinely empty SYSTEM block
A2 = '{ pkgs, ... }:\n{\n  environment.systemPackages = [ ];\n}\n'
r = add_package(A2, "htop", Path("/tmp"), SYSTEM)
check("A2 empty systemPackages: success ⇒ htop present",
      r.status != "success" or "htop" in r.content,
      f"status={r.status}, added={'htop' in r.content}")

# A3: DOTALL cross-block false detection — HOME plain block + with pkgs LATER
A3 = '''{ pkgs, ... }:
{
  home.packages = [
    pkgs.git
  ];
  environment.systemPackages = with pkgs; [
    vim
  ];
}
'''
r = add_package(A3, "htop", Path("/tmp"), HOME)
in_home_block = "htop" in r.content
check("A3 home plain + later 'with pkgs': success ⇒ htop added",
      r.status != "success" or in_home_block,
      f"status={r.status}, added={in_home_block}")

# A4: reverse — SYSTEM plain block + with pkgs later (in home block)
A4 = '''{ pkgs, ... }:
{
  environment.systemPackages = [
    pkgs.vim
  ];
  home.packages = with pkgs; [
    git
  ];
}
'''
r = add_package(A4, "htop", Path("/tmp"), SYSTEM)
check("A4 system plain + later 'with pkgs': success ⇒ htop added",
      r.status != "success" or "htop" in r.content,
      f"status={r.status}, added={'htop' in r.content}")

# A5: block name only inside a comment (no real block)
A5 = '{ pkgs, ... }:\n{\n  # home.packages is managed manually\n  home.username = "u";\n}\n'
r = add_package(A5, "htop", Path("/tmp"), HOME)
check("A5 comment-only mention: no silent success without a real block",
      r.status != "success" or ("home.packages = " in r.content and "htop" in r.content),
      f"status={r.status}, content_changed={r.content != A5}")

# A6: comment mimicking a block placed BEFORE the real block
A6 = '''{ pkgs, ... }:
{
  # environment.systemPackages = [ old-style ]
  environment.systemPackages = with pkgs; [
    git
  ];
}
'''
r = add_package(A6, "htop", Path("/tmp"), SYSTEM)
real_block_touched = "htop" in r.content and "# environment.systemPackages = [ old-style htop" not in r.content
check("A6 decoy comment block: insertion must hit the REAL block",
      r.status != "success" or real_block_touched,
      f"status={r.status}, decoy_corrupted={'old-style' in r.content and 'htop ]' in r.content and 'with pkgs' not in r.content.split(']')[0]}")

# ── [B] Formatting preservation ────────────────────────────────────────────
print("\n[B] formatting preservation")

B1 = '''{ pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    git   # vcs
    vim
  ];
}
'''
r = add_package(B1, "htop", Path("/tmp"), SYSTEM)
check("B1 comment inside block preserved", r.status == "success" and "# vcs" in r.content)
check("B1 existing entries preserved", "git" in r.content and "vim" in r.content)

B2 = '{ pkgs, ... }:\n{\n\thome.packages = with pkgs; [\n\t\tgit\n\t];\n}\n'
r = add_package(B2, "htop", Path("/tmp"), HOME)
check("B2 tab indentation: added with matching indent",
      r.status == "success" and "\t\thtop" in r.content, repr(r.content[:80]))

# ── [C] Duplicates ─────────────────────────────────────────────────────────
print("\n[C] duplicate handling")

C1 = '{ pkgs, ... }:\n{\n  environment.systemPackages = with pkgs; [\n    git\n  ];\n}\n'
r1 = add_package(C1, "git", Path("/tmp"), SYSTEM)
r2 = add_package(r1.content, "git", Path("/tmp"), SYSTEM)
count = r2.content.count("git")
check("C1 adding an existing package must not duplicate it",
      r2.status != "success" or count == 1,
      f"status={r2.status}, occurrences={count}")

# ── [D] Removal ────────────────────────────────────────────────────────────
print("\n[D] removal")

D1 = '{ pkgs, ... }:\n{\n  home.packages = with pkgs; [\n    git\n    vim\n  ];\n}\n'
out, found = remove_package(D1, "git", Path("/tmp"), HOME)
check("D1 remove existing: found, others kept",
      found and "git" not in out and "vim" in out)

out, found = remove_package(D1, "nonexistent", Path("/tmp"), HOME)
check("D2 remove nonexistent: not found, content unchanged",
      not found and out == D1)

out, found = remove_package(D1.replace("git", "pkgs.git"), "git", Path("/tmp"), HOME)
check("D3 pkgs.-prefixed line removable by bare name",
      found and "pkgs.git" not in out)

D4 = D1.replace("    git", "    git # note")
out, found = remove_package(D4, "git", Path("/tmp"), HOME)
check("D4 line with trailing comment removable",
      found, "commented-line removal (record actual behavior)")

# ── [E] External imports ───────────────────────────────────────────────────
print("\n[E] external import handling (Beta contract: unsupported_external)")

with tempfile.TemporaryDirectory() as td:
    (Path(td) / "pkgs.nix").write_text(
        '{\n  environment.systemPackages = with pkgs; [\n    git\n  ];\n}\n')
    host = '{ pkgs, ... }:\n{\n  environment.systemPackages = import ./pkgs.nix;\n}\n'
    r = add_package(host, "htop", Path(td), SYSTEM)
    ext = (Path(td) / "pkgs.nix").read_text()
    check("E1 external import: unsupported_external, host unchanged, external file untouched",
          r.status == "unsupported_external" and r.content == host and "htop" not in ext,
          f"status={r.status}, host_changed={r.content != host}, ext_has_htop={'htop' in ext}")

with tempfile.TemporaryDirectory() as td:
    sub = Path(td) / "sub"; sub.mkdir()
    (sub / "pkgs.nix").write_text(
        '{\n  environment.systemPackages = with pkgs; [\n    git\n  ];\n}\n')
    host = '{ pkgs, ... }:\n{\n  environment.systemPackages = import ../sub/pkgs.nix;\n}\n'
    try:
        r = add_package(host, "htop", Path(td), SYSTEM)
        ext = (sub / "pkgs.nix").read_text()
        check("E2 ../ relative import: unsupported_external, nothing modified",
              r.status == "unsupported_external" and r.content == host and "htop" not in ext,
              f"status={r.status}, ext_has_htop={'htop' in ext}")
    except Exception as e:
        check("E2 ../ relative import: unsupported_external, nothing modified", False, f"{type(e).__name__}: {e}")

# ── [F] Malformed input ────────────────────────────────────────────────────
print("\n[F] malformed input")

F1 = '{ pkgs, ... }:\n{\n  home.packages = with pkgs; [\n    git\n}\n'  # unclosed [
r = add_package(F1, "htop", Path("/tmp"), HOME)
check("F1 unclosed bracket: must not report clean success",
      r.status != "success" or r.content == F1,
      f"status={r.status}, mangled={r.content != F1}")

F2 = ""  # empty file
r = add_package(F2, "htop", Path("/tmp"), HOME)
check("F2 empty file: must not report clean success",
      r.status != "success" or r.content.strip() != "",
      f"status={r.status}, produced={r.content!r:.60}")

# ── [G] Boundary size ──────────────────────────────────────────────────────
print("\n[G] boundary size")

many = ", ".join(f"p{i}" for i in range(1000))
G1 = '{ pkgs, ... }:\n{\n  home.packages = with pkgs; [\n    ' + many + '\n  ];\n}\n'
t0 = time.time()
r = add_package(G1, "htop", Path("/tmp"), HOME)
out, found = remove_package(r.content, "htop", Path("/tmp"), HOME)
dt = time.time() - t0
check(f"G1 1000-package block add+remove < 2s (took {dt:.2f}s)",
      found and dt < 2.0 and "p999" in out)

# ── [H] Formatting-variation property ─────────────────────────────────────
print("\n[H] property: success ⇒ reference present (formatting variations)")

violations = []
variants = {
    "2-space-indent": '{ pkgs, ... }:\n{\n  home.packages = [ ];\n}\n',
    "4-space-indent": '{ pkgs, ... }:\n    {\n    home.packages = [ ];\n    }\n',
    "no-spaces": '{pkgs,...}:{home.packages=[];}',
    "newline-in-list": '{ pkgs, ... }:\n{\n  home.packages = [\n\n  ];\n}\n',
    "trailing-space-eq": '{ pkgs, ... }:\n{\n  home.packages  =  [ ];\n}\n',
    "block-last-no-nl": '{ pkgs, ... }:\n{\n  home.packages = [ ];\n}',
    "with-pkgs-same-line": '{ pkgs, ... }:\n{\n  home.packages = with pkgs; [ git ];\n}\n',
    "comment-above-block": '{ pkgs, ... }:\n{\n  # packages\n  home.packages = [ ];\n}\n',
}
for label, content in variants.items():
    r = add_package(content, "htop", Path("/tmp"), HOME)
    ok = r.status != "success" or "htop" in r.content
    if not ok:
        violations.append(label)
    print(f"    {'✓' if ok else '✗'} {label}: status={r.status} added={'htop' in r.content}")
check("H1 zero silent-no-op violations across variations",
      not violations, f"violations: {violations}")

# ── [I] Dead-code evidence (informational) ────────────────────────────────
print("\n[I] dead code (informational)")

import inspect
src = inspect.getsource(add_package)
check("I1 'empty' never reaches a handler — rejected at the support gate",
      "add_package_empty(" not in src and "unsupported_" in src,
      "empty must map to unsupported_empty, not to any insertion handler")

print("\n" + "=" * 70)
print(f"RESULTS: {len(PASS)} passed, {len(FAIL)} failed (failures = findings)")
if FAIL:
    for f in FAIL:
        print(f"  ✗ FINDING: {f}")
print("=" * 70)
sys.exit(0)  # audit harness: always exit 0; findings live in the report
