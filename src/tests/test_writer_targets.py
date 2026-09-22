"""Target-aware writer regression tests.

Verifies that the parameterized writer operates correctly on BOTH
environment.systemPackages (SYSTEM) and home.packages (HOME), and that
the default (no block argument) preserves historical SYSTEM behavior
byte-for-byte.
"""
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from src.core.writer import (
    add_package, remove_package, is_package_exists, detect_format,
    add_package_with_pkgs, add_package_explicit_pkgs, add_package_empty,
    add_package_missing, add_flake_package,
)

SYSTEM = "environment.systemPackages"
HOME = "home.packages"

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f" — {detail}" if not cond else ""))


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


print("=" * 70)
print("WRITER TARGET REGRESSION TESTS")
print("=" * 70)

# ── detect_format ──────────────────────────────────────────────────────────
print("\n[1] detect_format — both blocks")

check("system with_pkgs", detect_format(SYS_WITH_PKGS) == "with_pkgs")
check("system with_pkgs (explicit block arg)",
      detect_format(SYS_WITH_PKGS, SYSTEM) == "with_pkgs")
check("home with_pkgs", detect_format(HOME_WITH_PKGS, HOME) == "with_pkgs")
check("home plain list → explicit_pkgs", detect_format(HOME_PLAIN, HOME) == "explicit_pkgs")
check("home missing block", detect_format(HOME_MISSING, HOME) == "missing")
# default arg must NOT see home.packages as system
check("default block ignores home.packages (missing for SYSTEM)",
      detect_format(HOME_WITH_PKGS) == "missing")
# cross-check: SYSTEM block missing when asking HOME
check("home block ignored when asking SYSTEM",
      detect_format(SYS_WITH_PKGS, HOME) == "missing")

# ── add_package ────────────────────────────────────────────────────────────
print("\n[2] add_package — SYSTEM (default, regression)")

result = add_package(SYS_WITH_PKGS, "htop", Path("/tmp"))
check("system default: success", result.status == "success")
check("system default: htop added", "htop" in result.content)
check("system default: git preserved", "git" in result.content)

print("\n[3] add_package — HOME with_pkgs")

result = add_package(HOME_WITH_PKGS, "htop", Path("/tmp"), HOME)
check("home with_pkgs: success", result.status == "success")
check("home with_pkgs: htop added", "htop" in result.content)
check("home with_pkgs: git preserved", "git" in result.content)
check("home with_pkgs: username preserved", 'home.username' in result.content)
# the add must NOT touch a systemPackages block even if one existed
both = SYS_WITH_PKGS.replace("}", "  home.packages = with pkgs; [ vim ];\n}")
result = add_package(both, "htop", Path("/tmp"), HOME)
check("home add leaves systemPackages untouched",
      result.content.count("htop") == 1 and "environment.systemPackages" in result.content)

print("\n[4] add_package — HOME plain list (explicit pkgs)")

result = add_package(HOME_PLAIN, "htop", Path("/tmp"), HOME)
check("home plain: success", result.status == "success")
check("home plain: pkgs.htop added (explicit form)", "pkgs.htop" in result.content)
check("home plain: pkgs.git preserved", "pkgs.git" in result.content)

print("\n[5] add_package — HOME block missing → creates home.packages, not systemPackages")

result = add_package(HOME_MISSING, "htop", Path("/tmp"), HOME)
check("home missing: success", result.status == "success")
check("home missing: creates home.packages block", "home.packages" in result.content)
check("home missing: does NOT create environment.systemPackages",
      "environment.systemPackages" not in result.content)
check("home missing: htop inside created block", "htop" in result.content)

# ── remove_package ─────────────────────────────────────────────────────────
print("\n[6] remove_package — both targets")

out, found = remove_package(SYS_WITH_PKGS, "git", Path("/tmp"))
check("system remove: found", found)
check("system remove: git gone", "git" not in out)

out, found = remove_package(HOME_WITH_PKGS, "git", Path("/tmp"), HOME)
check("home remove: found", found)
check("home remove: git gone", "git" not in out)
check("home remove: username preserved", "home.username" in out)

out, found = remove_package(HOME_PLAIN, "pkgs.git", Path("/tmp"), HOME)
check("home plain remove: found (pkgs. form)", found)

out, found = remove_package(HOME_WITH_PKGS, "nonexistent", Path("/tmp"), HOME)
check("home remove: not-found reported", not found)
check("home remove: content unchanged on not-found", out == HOME_WITH_PKGS)

# cross-target isolation: removing from HOME must not touch SYSTEM
both = SYS_WITH_PKGS.replace("}", "  home.packages = with pkgs; [ git ];\n}")
out, found = remove_package(both, "git", Path("/tmp"), HOME)
check("home remove leaves systemPackages git intact",
      found and out.count("git") >= 1 and "environment.systemPackages" in out)

# ── is_package_exists ──────────────────────────────────────────────────────
print("\n[7] is_package_exists — both targets")

check("system: detects git", is_package_exists(SYS_WITH_PKGS, "git", Path("/tmp")))
check("system: rejects missing", not is_package_exists(SYS_WITH_PKGS, "htop", Path("/tmp")))
check("home: detects git", is_package_exists(HOME_WITH_PKGS, "git", Path("/tmp"), HOME))
check("home: rejects missing", not is_package_exists(HOME_WITH_PKGS, "htop", Path("/tmp"), HOME))
check("home: SYSTEM query on home-only file → False",
      not is_package_exists(HOME_WITH_PKGS, "git", Path("/tmp")))
check("home: HOME query on system-only file → False",
      not is_package_exists(SYS_WITH_PKGS, "git", Path("/tmp"), HOME))

# ── empty block ────────────────────────────────────────────────────────────
print("\n[8] empty blocks")

sys_empty = "{ pkgs, ... }:\n{\n  environment.systemPackages = [ ];\n}\n"
result = add_package(sys_empty, "htop", Path("/tmp"))
check("system empty: success", result.status == "success")

home_empty = "{ pkgs, ... }:\n{\n  home.packages = [ ];\n}\n"
result = add_package(home_empty, "htop", Path("/tmp"), HOME)
check("home empty: success", result.status == "success")
check("home empty: stays home.packages", "home.packages" in result.content)
check("home empty: no systemPackages leak",
      "environment.systemPackages" not in result.content)

# ── add_flake_package home.packages with-pkgs fix ──────────────────────────
print("\n[9] add_flake_package — home.packages = with pkgs; [ (the fixed case)")

home_with = '''{ pkgs, ... }:
{
  home.packages = with pkgs; [
    git
  ];
}
'''
out = add_flake_package(home_with, "test-flake", "default")
check("flake ref added to home.packages with-pkgs form",
      "inputs.test-flake.packages" in out)
check("existing git preserved", "git" in out)

home_plain = '''{ pkgs, ... }:
{
  home.packages = [
    pkgs.git
  ];
}
'''
out = add_flake_package(home_plain, "test-flake", "default")
check("flake ref added to home.packages plain form (regression)",
      "inputs.test-flake.packages" in out)

# system fallback still works when no home.packages present
out = add_flake_package(SYS_WITH_PKGS, "test-flake", "default")
check("flake ref falls back to systemPackages when no home block",
      "inputs.test-flake.packages" in out and "environment.systemPackages" in out)

# ── default-arg byte-identity (SYSTEM regression) ──────────────────────────
print("\n[10] default argument ≡ explicit SYSTEM (byte-identical)")

for fn_name, fn, extra in [
    ("add_package", add_package, ("htop",)),
    ("remove_package", remove_package, ("git",)),
    ("is_package_exists", is_package_exists, ("git",)),
    ("detect_format", detect_format, ()),
]:
    default_out = fn(SYS_WITH_PKGS, *extra, Path("/tmp")) if fn_name != "detect_format" else fn(SYS_WITH_PKGS)
    explicit_out = fn(SYS_WITH_PKGS, *extra, Path("/tmp"), SYSTEM) if fn_name != "detect_format" else fn(SYS_WITH_PKGS, SYSTEM)
    check(f"{fn_name}: default == explicit SYSTEM", default_out == explicit_out)

# ── overlay reference namespace (claude-desktop-nix regression) ────────────
print("\n[11] add_flake_overlay — inputs. namespace (both insertion paths)")

from src.core.writer import add_flake_overlay, remove_flake_reference

OVERLAY_EXISTING = '''{ config, pkgs, inputs, ... }:
{
  nixpkgs.overlays = [
    inputs.other-flake.overlays.default
  ];
}
'''
out = add_flake_overlay(OVERLAY_EXISTING, "claude-desktop-nix", "default")
check("overlay existing block: generates inputs.<name>.overlays.default",
      "inputs.claude-desktop-nix.overlays.default" in out)
check("overlay existing block: no bare <name>.overlays form",
      "claude-desktop-nix.overlays" not in out.replace("inputs.claude-desktop-nix.overlays", ""))
check("overlay existing block: unrelated overlay preserved",
      "inputs.other-flake.overlays.default" in out)

NO_OVERLAY_BLOCK = '''{ config, pkgs, inputs, ... }:
{
  environment.systemPackages = with pkgs; [
    git
  ];
}
'''
out = add_flake_overlay(NO_OVERLAY_BLOCK, "claude-desktop-nix", "default")
check("overlay new block: block created", "nixpkgs.overlays = [" in out)
check("overlay new block: uses inputs.<name>.overlays.default",
      "inputs.claude-desktop-nix.overlays.default" in out)
check("overlay new block: no bare form",
      "claude-desktop-nix.overlays" not in out.replace("inputs.claude-desktop-nix.overlays", ""))

print("\n[12] remove_flake_reference — overlay removal")

overlay_installed = '''{ config, pkgs, inputs, ... }:
{
  nixpkgs.overlays = [
    inputs.claude-desktop-nix.overlays.default
  ];
}
'''
out, found = remove_flake_reference(overlay_installed, "claude-desktop-nix")
check("overlay reference removed", found)
check("overlay removal: flake name gone from content", "claude-desktop-nix" not in out)
check("overlay removal: structure preserved", "nixpkgs.overlays = [" in out)

mixed = '''{ config, pkgs, inputs, ... }:
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
out, found = remove_flake_reference(mixed, "claude-desktop-nix")
check("mixed: target overlay removed", found and "claude-desktop-nix" not in out)
check("mixed: unrelated overlay preserved",
      "inputs.other-flake.overlays.default" in out)
check("mixed: unrelated package reference preserved",
      "inputs.zen-browser.packages.${pkgs.stdenv.hostPlatform.system}.default" in out)

print("\n[13] package references unchanged (regression)")

pkg_content = '''{ config, pkgs, inputs, ... }:
{
  environment.systemPackages = with pkgs; [
    inputs.zen-browser.packages.${pkgs.stdenv.hostPlatform.system}.default
  ];
}
'''
out, found = remove_flake_reference(pkg_content, "zen-browser")
check("package reference still removed by name",
      found and "zen-browser" not in out)
out, found = remove_flake_reference(pkg_content, "claude-desktop-nix")
check("package removal does not match other flakes' references",
      not found and out == pkg_content)

# SYSTEM/HOME target behavior unchanged (Step 3/4 regression, quick re-check)
sys_with_overlay = SYS_WITH_PKGS.replace(
    "}", "  nixpkgs.overlays = [\n    inputs.repo.overlays.default\n  ];\n}")
out = add_flake_overlay(sys_with_overlay, "new-flake", "default")
check("SYSTEM content: overlay add preserves systemPackages block",
      "environment.systemPackages" in out and "git" in out)
home_with_overlay = HOME_WITH_PKGS.replace(
    "}", "  nixpkgs.overlays = [\n    inputs.repo.overlays.default\n  ];\n}")
out = add_flake_overlay(home_with_overlay, "new-flake", "default")
check("HOME content: overlay add preserves home.packages block",
      "home.packages" in out and "git" in out)


print("\n" + "=" * 70)
print(f"RESULTS: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    for f in FAIL: print(f"  ✗ {f}")
print("=" * 70)
sys.exit(1 if FAIL else 0)
