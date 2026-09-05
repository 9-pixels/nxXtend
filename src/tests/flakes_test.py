import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from src.api.flakes import flake_parse_packages, extract_block

# ── extract_block ──────────────────────────────────────────────────────────────

def test_extract_block_simple():
    content = "foo = { a = 1; b = 2; }"
    pos = content.index("{")
    result = extract_block(content, pos)
    assert result == " a = 1; b = 2; ", f"got: {result!r}"

def test_extract_block_nested():
    content = "foo = { a = { x = 1; }; b = 2; }"
    pos = content.index("{")
    result = extract_block(content, pos)
    assert result == " a = { x = 1; }; b = 2; ", f"got: {result!r}"

def test_extract_block_unbalanced():
    content = "foo = { a = 1;"
    pos = content.index("{")
    result = extract_block(content, pos)
    assert result is None

# ── flake_parse_packages ───────────────────────────────────────────────────────

def test_pattern1_direct():
    content = """
    packages.x86_64-linux = {
      hello = pkgs.hello;
      cowsay = pkgs.cowsay;
    };
    """
    result = flake_parse_packages(content)
    assert result == ["hello", "cowsay"], f"got: {result}"

def test_pattern1_with_nested():
    content = """
    packages.x86_64-linux = {
      nh = pkgs.callPackage ./package.nix { inherit rev; };
    };
    """
    result = flake_parse_packages(content)
    assert result == ["nh"], f"got: {result}"

def test_pattern2_attrset():
    content = """
    packages = {
      x86_64-linux = {
        hello = pkgs.hello;
      };
    };
    """
    result = flake_parse_packages(content)
    assert result == ["hello"], f"got: {result}"

def test_pattern3_forAllSystems():
    content = """
    packages = forAllSystems (pkgs: {
      nh = pkgs.callPackage ./package.nix { inherit rev; };
      default = self.packages.x86_64-linux.nh;
    });
    """
    result = flake_parse_packages(content)
    assert result == ["nh"], f"got: {result}"

def test_pattern3_eachDefaultSystem():
    content = """
    packages = eachDefaultSystem (system: {
      hello = pkgs.hello;
      cowsay = pkgs.cowsay;
    });
    """
    result = flake_parse_packages(content)
    assert result == ["hello", "cowsay"], f"got: {result}"

def test_pattern3_genAttrs():
    content = """
    packages = lib.genAttrs systems (system: {
      hello = pkgs.hello;
    });
    """
    result = flake_parse_packages(content)
    assert result == ["hello"], f"got: {result}"

def test_pattern4_perSystem():
    content = """
    perSystem = { pkgs, ... }: {
      packages = {
        hello = pkgs.hello;
        cowsay = pkgs.cowsay;
      };
    };
    """
    result = flake_parse_packages(content)
    assert result == ["hello", "cowsay"], f"got: {result}"

def test_import_returns_none():
    content = """
    packages = forAllSystems (pkgs: import ./pkgs { inherit pkgs; });
    """
    result = flake_parse_packages(content)
    assert result is None, f"got: {result}"

def test_no_packages_returns_none():
    content = """
    outputs = { self, nixpkgs }: {
      devShells.x86_64-linux.default = pkgs.mkShell {};
    };
    """
    result = flake_parse_packages(content)
    assert result is None, f"got: {result}"

def test_default_excluded():
    content = """
    packages.x86_64-linux = {
      hello = pkgs.hello;
      default = pkgs.hello;
    };
    """
    result = flake_parse_packages(content)
    assert "default" not in result, f"got: {result}"

# ── runner ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_extract_block_simple,
        test_extract_block_nested,
        test_extract_block_unbalanced,
        test_pattern1_direct,
        test_pattern1_with_nested,
        test_pattern2_attrset,
        test_pattern3_forAllSystems,
        test_pattern3_eachDefaultSystem,
        test_pattern3_genAttrs,
        test_pattern4_perSystem,
        test_import_returns_none,
        test_no_packages_returns_none,
        test_default_excluded,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            print(f"  ✓ {test.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ {test.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n  {passed} passed, {failed} failed")