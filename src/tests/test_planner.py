import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from src.flakes.planner import build_plan
from src.flakes.models import FlakeSource, FlakeOutput


def test_packages_install():
    source = FlakeSource(url="github:NixOS/nixpkgs")
    output = FlakeOutput(name="hello", type="packages", attribute="packages.x86_64-linux.hello")
    plan = build_plan(source, output, "x86_64-linux")
    assert plan.action == "install"


def test_legacy_packages_install():
    source = FlakeSource(url="github:NixOS/nixpkgs")
    output = FlakeOutput(name="legacy-pkg", type="legacyPackages", attribute="legacyPackages.x86_64-linux.legacy-pkg")
    plan = build_plan(source, output, "x86_64-linux")
    assert plan.action == "install"


def test_nixos_modules_configure():
    source = FlakeSource(url="github:some/module")
    output = FlakeOutput(name="my-module", type="nixosModules", attribute="nixosModules.my-module")
    plan = build_plan(source, output, "x86_64-linux")
    assert plan.action == "configure"


def test_home_manager_modules_configure_home():
    source = FlakeSource(url="github:some/home-module")
    output = FlakeOutput(name="my-home-mod", type="homeManagerModules", attribute="homeManagerModules.my-home-mod")
    plan = build_plan(source, output, "x86_64-linux")
    assert plan.action == "configure_home"


def test_overlays_overlay():
    source = FlakeSource(url="github:some/overlay")
    output = FlakeOutput(name="default", type="overlays", attribute="overlays.default")
    plan = build_plan(source, output, "x86_64-linux")
    assert plan.action == "overlay"


def test_apps_unsupported():
    source = FlakeSource(url="github:some/app")
    output = FlakeOutput(name="myapp", type="apps", attribute="apps.x86_64-linux.myapp")
    plan = build_plan(source, output, "x86_64-linux")
    assert plan.action == "unsupported"


def test_devshells_unsupported():
    source = FlakeSource(url="github:some/shell")
    output = FlakeOutput(name="default", type="devShells", attribute="devShells.x86_64-linux.default")
    plan = build_plan(source, output, "x86_64-linux")
    assert plan.action == "unsupported"


def test_unknown_type_unsupported():
    source = FlakeSource(url="github:some/thing")
    output = FlakeOutput(name="unknown", type="customType", attribute="customType.unknown")
    plan = build_plan(source, output, "x86_64-linux")
    assert plan.action == "unsupported"


if __name__ == "__main__":
    tests = [
        test_packages_install,
        test_legacy_packages_install,
        test_nixos_modules_configure,
        test_home_manager_modules_configure_home,
        test_overlays_overlay,
        test_apps_unsupported,
        test_devshells_unsupported,
        test_unknown_type_unsupported,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n  {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
