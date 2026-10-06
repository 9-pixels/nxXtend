import sys
import os
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from flakes.discovery import discover, classify
from flakes.models import FlakeSource, FlakeOutput

# ── Mock data ──────────────────────────────────────────────────────────────────

MOCK_SHOW_OUTPUT = {
    "packages": {
        "x86_64-linux": {
            "vim": {},
            "default": {},
            "git": {},
            "curl": {}
        },
        "aarch64-linux": {
            "vim-aarch": {},
            "someArmOnly": {}
        }
    },
    "devShells": {
        "x86_64-linux": {
            "myCustom": {},
            "default": {}
        }
    },
    "apps": {
        "x86_64-linux": {
            "myapp": {},
            "default": {}
        }
    },
    "nixosModules": {
        "default": {},
        "custom-module": {}
    },
    "homeManagerModules": {
        "default": {}
    },
    "overlays": {
        "default": {},
        "extra-overlay": {}
    },
    "checks": {
        "x86_64-linux": {
            "check1": {}
        }
    }
}


def fake_run(*args, **kwargs):
    result = MagicMock()
    if "flake" in args[0] and "show" in args[0]:
        result.returncode = 0
        result.stdout = json.dumps(MOCK_SHOW_OUTPUT)
        result.stderr = ""
    elif "eval" in args[0]:
        result.returncode = 0
        result.stdout = "x86_64-linux"
        result.stderr = ""
    else:
        result.returncode = 1
        result.stdout = ""
        result.stderr = "unknown command"
    return result


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_devshells_discovered():
    source = FlakeSource(url="github:test/multi-output-flake")
    with patch("flakes.discovery.subprocess.run", side_effect=fake_run):
        outputs = discover(source)
    devshells = [o for o in outputs if o.type == "devShells"]
    assert len(devshells) == 2, f"expected 2 devShells, got {len(devshells)}"
    assert "default" in [o.name for o in devshells]
    assert "myCustom" in [o.name for o in devshells]


def test_no_wrong_system_leak():
    source = FlakeSource(url="github:test/multi-output-flake")
    with patch("flakes.discovery.subprocess.run", side_effect=fake_run):
        outputs = discover(source)
    aarch = [o for o in outputs if o.system == "aarch64-linux"]
    assert len(aarch) == 0, f"aarch64-linux leaked: {[o.name for o in aarch]}"


def test_default_first_in_each_type():
    source = FlakeSource(url="github:test/multi-output-flake")
    with patch("flakes.discovery.subprocess.run", side_effect=fake_run):
        outputs = discover(source)
    from collections import defaultdict
    by_type = defaultdict(list)
    for o in outputs:
        by_type[o.type].append(o)
    for t, outs in by_type.items():
        if any(o.name == "default" for o in outs):
            assert outs[0].name == "default", f"default not first in {t}: {[o.name for o in outs]}"


def test_order_preserved_for_non_default():
    source = FlakeSource(url="github:test/multi-output-flake")
    with patch("flakes.discovery.subprocess.run", side_effect=fake_run):
        outputs = discover(source)
    pkgs = [o.name for o in outputs if o.type == "packages"]
    assert pkgs == ["default", "vim", "git", "curl"], f"order wrong: {pkgs}"


def test_non_systemic_types_have_no_system():
    source = FlakeSource(url="github:test/multi-output-flake")
    with patch("flakes.discovery.subprocess.run", side_effect=fake_run):
        outputs = discover(source)
    non_systemic_types = {"nixosModules", "homeManagerModules", "overlays"}
    for o in outputs:
        if o.type in non_systemic_types:
            assert o.system is None, f"{o.type}.{o.name} has system={o.system}"


def test_checks_ignored():
    source = FlakeSource(url="github:test/multi-output-flake")
    with patch("flakes.discovery.subprocess.run", side_effect=fake_run):
        outputs = discover(source)
    checks = [o for o in outputs if o.type == "checks"]
    assert len(checks) == 0, f"checks not ignored: {checks}"


def test_all_known_types_present():
    source = FlakeSource(url="github:test/multi-output-flake")
    with patch("flakes.discovery.subprocess.run", side_effect=fake_run):
        outputs = discover(source)
    types_found = {o.type for o in outputs}
    expected = {"packages", "devShells", "apps", "nixosModules", "homeManagerModules", "overlays"}
    assert types_found == expected, f"types mismatch: got {types_found}, expected {expected}"


def test_overlays_not_unsupported():
    """overlays should not be classified as unsupported and should get the correct classification"""
    output = FlakeOutput(name="default", type="overlays", attribute="overlays.default")
    result = classify(output)
    assert result != "unsupported", f"overlays classified as unsupported, got: {result}"
    assert result == "overlay", f"expected 'overlay', got: {result}"


# ── Runner ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_devshells_discovered,
        test_no_wrong_system_leak,
        test_default_first_in_each_type,
        test_order_preserved_for_non_default,
        test_non_systemic_types_have_no_system,
        test_checks_ignored,
        test_all_known_types_present,
        test_overlays_not_unsupported,
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
    if failed:
        sys.exit(1)
