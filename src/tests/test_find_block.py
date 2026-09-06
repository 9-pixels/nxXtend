import sys
import os
from datetime import date
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from src.api.flakes import _find_block

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
RESULTS_FILE = os.path.join(RESULTS_DIR, f"{date.today()}.txt")


def run_test(name: str, fn) -> bool:
    try:
        fn()
        print(f"  ✓ {name}")
        return True
    except AssertionError as e:
        print(f"  ✗ {name}: {e}")
        return False
    except Exception as e:
        print(f"  ✗ {name}: {type(e).__name__}: {e}")
        return False


# ── tests ──────────────────────────────────────────────────────────────────────

def test_pattern1_direct():
    content = """
    packages.x86_64-linux = {
      hello = pkgs.hello;
      cowsay = pkgs.cowsay;
    };
    """
    block = _find_block(content, "packages")
    assert block is not None
    assert "hello" in block
    assert "cowsay" in block

def test_pattern2_attrset():
    content = """
    packages = {
      x86_64-linux = {
        hello = pkgs.hello;
      };
    };
    """
    block = _find_block(content, "packages")
    assert block is not None
    assert "hello" in block

def test_pattern3_forAllSystems():
    content = """
    packages = forAllSystems (pkgs: {
      nh = pkgs.callPackage ./package.nix { };
    });
    """
    block = _find_block(content, "packages")
    assert block is not None
    assert "nh" in block

def test_pattern3_genAttrs():
    content = """
    packages = lib.genAttrs systems (system: {
      hello = pkgs.hello;
    });
    """
    block = _find_block(content, "packages")
    assert block is not None
    assert "hello" in block

def test_pattern4_perSystem():
    content = """
    perSystem = { pkgs, ... }: {
      packages = {
        hello = pkgs.hello;
      };
    };
    """
    block = _find_block(content, "packages")
    assert block is not None
    assert "hello" in block

def test_pattern_not_found():
    content = """
    devShells = forAllSystems (pkgs: {
      default = pkgs.mkShell {};
    });
    """
    block = _find_block(content, "packages")
    assert block is None

def test_nixos_modules():
    content = """
    nixosModules = {
      default = import ./modules/default.nix;
    };
    """
    block = _find_block(content, "nixosModules")
    assert block is not None

def test_overlays():
    content = """
    overlays.default = final: _: {
      nh = final.callPackage ./package.nix { };
    };
    """
    block = _find_block(content, "overlays")
    assert block is not None

def test_no_partial_match():
    content = """
    nixosModules = {
      default = ./modules.nix;
    };
    """
    # homeModules لا يجب أن يطابق nixosModules
    block = _find_block(content, "homeModules")
    assert block is None

def test_nested_braces():
    content = """
    packages = forAllSystems (pkgs: {
      nh = pkgs.callPackage ./package.nix { inherit rev; };
      default = self.packages.x86_64-linux.nh;
    });
    """
    block = _find_block(content, "packages")
    assert block is not None
    assert "nh" in block


# ── runner ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        ("pattern1 — direct system attr", test_pattern1_direct),
        ("pattern2 — attrset", test_pattern2_attrset),
        ("pattern3 — forAllSystems", test_pattern3_forAllSystems),
        ("pattern3 — genAttrs", test_pattern3_genAttrs),
        ("pattern4 — perSystem", test_pattern4_perSystem),
        ("pattern not found", test_pattern_not_found),
        ("nixosModules", test_nixos_modules),
        ("overlays", test_overlays),
        ("no partial match", test_no_partial_match),
        ("nested braces", test_nested_braces),
    ]

    passed = 0
    failed = 0
    lines = [f"test_find_block — {date.today()}\n"]

    for name, fn in tests:
        ok = run_test(name, fn)
        if ok:
            passed += 1
            lines.append(f"  ✓ {name}")
        else:
            failed += 1
            lines.append(f"  ✗ {name}")

    summary = f"\n  {passed} passed, {failed} failed"
    print(summary)
    lines.append(summary)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(RESULTS_FILE, "a") as f:
        f.write("\n".join(lines) + "\n\n")

    print(f"\n  results saved to {RESULTS_FILE}")