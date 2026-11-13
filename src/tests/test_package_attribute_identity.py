"""Package attribute identity tests (package_pname vs package_attr_name).

The Nix reference identity of a package is its attribute path
(``package_attr_name``), never its upstream derivation pname
(``package_pname``). They are often equal but are not interchangeable:

    package_pname     = "nx"        -> pkgs.nx        (a DIFFERENT package)
    package_attr_name = "nxXtend"   -> pkgs.nxXtend   (the intended one)

These tests pin that contract at every stage of the pipeline: API mapping,
package model, reference construction, duplicate detection, collision
detection and search-result deduplication.

Migrated from unittest.TestCase to plain pytest classes; every test method
maps 1:1 to a collected pytest test. The API search helper now targets the
``api.*`` namespace used by the application instead of ``src.api.*``, so the
modules are no longer loaded twice under two names.
"""
import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.manager import deduplicate
from core.writer import (
    build_package_reference, resolve_identity,
    is_package_exists, is_package_name_taken,
)
from models.package import Package

TP = Path("/tmp")

# The canonical example: attribute differs from pname.
ATTR = "nxXtend"
PNAME = "nx"


def _api_hit(attr_name, pname, pversion="1.0", attr_set=None):
    """Build one search.nixos.org hit as the API returns it."""
    src = {
        "package_attr_name": attr_name,
        "package_pname": pname,
        "package_pversion": pversion,
        "package_description": "desc",
    }
    if attr_set is not None:
        src["package_attr_set"] = attr_set
    return {"_source": src}


def _mock_response(hits):
    resp = MagicMock()
    resp.json.return_value = {"hits": {"hits": hits}}
    return resp


def search_module(module, hits):
    """Call the real API search function with `requests.post` mocked."""
    with patch(f"api.{module}.requests.post", return_value=_mock_response(hits)):
        mod = importlib.import_module(f"api.{module}")
        return mod.stable_search("q") if module == "stable" else mod.unstable_search("q")


class TestApiMapsAttributeFromAttrName:
    """Case A/D/E — stable and unstable must map attribute <- package_attr_name."""

    def test_stable_attribute_is_attr_name_not_pname(self):
        pkgs = search_module("stable", [_api_hit(ATTR, PNAME)])
        assert len(pkgs) == 1
        assert pkgs[0].attribute == ATTR
        assert pkgs[0].name == PNAME

    def test_unstable_attribute_is_attr_name_not_pname(self):
        pkgs = search_module("unstable", [_api_hit(ATTR, PNAME)])
        assert len(pkgs) == 1
        assert pkgs[0].attribute == ATTR
        assert pkgs[0].name == PNAME

    def test_stable_and_unstable_agree_on_identity(self):
        hits = [_api_hit(ATTR, PNAME)]
        s = search_module("stable", hits)[0]
        u = search_module("unstable", hits)[0]
        assert s.attribute == u.attribute
        assert s.name == u.name
        assert s.source == "stable"
        assert u.source == "unstable"

    def test_missing_attr_name_record_is_skipped(self):
        """Case E — no fallback to package_pname; malformed records are dropped."""
        hits = [
            _api_hit("ripgrep", "ripgrep"),
            {"_source": {"package_pname": PNAME, "package_pversion": "1.0",
                         "package_description": "d"}},          # no attr_name
            {"_source": {"package_attr_name": "", "package_pname": "x",
                         "package_pversion": "1.0", "package_description": "d"}},
        ]
        pkgs = search_module("stable", hits)
        assert [p.attribute for p in pkgs] == ["ripgrep"]
        # the pname must never leak in as an identity
        assert PNAME not in [p.attribute for p in pkgs]

    def test_unstable_missing_attr_name_record_is_skipped(self):
        hits = [{"_source": {"package_pname": PNAME, "package_pversion": "1.0",
                             "package_description": "d"}}]
        assert search_module("unstable", hits) == []


class TestPackageModelKeepsBothIdentities:
    """Case C — name (pname) must survive as metadata, not become an alias."""

    def test_name_and_attribute_are_independent_fields(self):
        p = Package(name=PNAME, version="1.0", description="d",
                    source="stable", type=None, attribute=ATTR)
        assert p.name == PNAME
        assert p.attribute == ATTR
        assert p.name != p.attribute

    def test_name_is_not_overwritten_by_attribute(self):
        p = Package(name=PNAME, version="1.0", description="d",
                    source="stable", type=None, attribute=ATTR)
        # building a reference must not mutate the display identity
        build_package_reference(p.attribute, p.source, "explicit_pkgs")
        assert p.name == PNAME


class TestReferenceConstruction:
    """Cases A/B — the attribute path is written, never the pname."""

    def test_case_a_attr_with_pkgs(self):
        assert build_package_reference(ATTR, "stable", "with_pkgs") == ATTR

    def test_case_a_attr_explicit(self):
        assert build_package_reference(ATTR, "stable", "explicit_pkgs") == f"pkgs.{ATTR}"

    def test_case_a_never_produces_pname_reference(self):
        ref = build_package_reference(ATTR, "stable", "explicit_pkgs")
        # Exact match, not substring: "nx" is a prefix of "nxXtend", so a
        # substring check would false-positive here.
        assert ref != f"pkgs.{PNAME}"
        assert ref == f"pkgs.{ATTR}"
        assert ref.split(".")[-1] != PNAME

    def test_case_b_nested_attribute_stays_intact(self):
        attr = "python314Packages.xstatic-asciinema-player"
        assert build_package_reference(attr, "stable", "explicit_pkgs") == f"pkgs.{attr}"

    def test_case_b_nested_attribute_not_truncated(self):
        ref = build_package_reference(
            "python314Packages.xstatic-asciinema-player", "stable", "explicit_pkgs")
        assert "python314Packages.xstatic-asciinema-player" in ref
        assert ref != "pkgs.xstatic-asciinema-player"

    def test_case_b_no_duplicated_attribute_set(self):
        ref = build_package_reference(
            "python314Packages.xstatic-asciinema-player", "stable", "explicit_pkgs")
        assert ref.count("python314Packages") == 1

    def test_unstable_nested_attribute(self):
        assert build_package_reference(
            "python314Packages.xstatic-asciinema-player",
            "unstable", "with_pkgs", "unstable") == \
            "unstable.python314Packages.xstatic-asciinema-player"


class TestIdentityDrivesDuplicateAndCollisionDetection:
    """Case D/F/H/I — detection must use the attribute, never the pname."""

    WRONG_PKG_INSTALLED = '''{ pkgs, ... }: {
  environment.systemPackages = with pkgs; [
    nx
  ];
}'''

    RIGHT_PKG_INSTALLED = '''{ pkgs, ... }: {
  environment.systemPackages = with pkgs; [
    nxXtend
  ];
}'''

    def test_case_i_pname_is_not_the_identity(self):
        """`nx` installed must NOT satisfy a request for `nxXtend`."""
        assert not is_package_exists(
            self.WRONG_PKG_INSTALLED, ATTR, TP, source="stable")

    def test_case_h_installed_attribute_is_recognised(self):
        assert is_package_exists(
            self.RIGHT_PKG_INSTALLED, ATTR, TP, source="stable")

    def test_case_i_pname_does_not_collide(self):
        """An installed `nx` must not block installing `nxXtend`."""
        assert not is_package_name_taken(self.WRONG_PKG_INSTALLED, ATTR, TP)

    def test_resolve_identity_uses_attribute(self):
        ident = resolve_identity(ATTR, "stable")
        assert ident.reference == ATTR
        assert ident.name == ATTR
        assert ident.reference != PNAME

    def test_nested_attribute_identity(self):
        ident = resolve_identity(
            "python314Packages.xstatic-asciinema-player", "stable")
        assert ident.reference == "python314Packages.xstatic-asciinema-player"


class TestManagerDeduplication:
    """Case D — dedup keys on attribute, so same-pname packages both survive."""

    def _pkg(self, attr, pname, source="stable"):
        return Package(name=pname, version="1.0", description="d",
                       source=source, type=None, attribute=attr)

    def test_same_pname_different_attribute_both_kept(self):
        pkgs = [self._pkg(PNAME, PNAME), self._pkg(ATTR, PNAME)]
        assert len(deduplicate(pkgs)) == 2

    def test_exact_duplicate_removed(self):
        pkgs = [self._pkg(ATTR, PNAME), self._pkg(ATTR, PNAME)]
        assert len(deduplicate(pkgs)) == 1

    def test_nested_attr_set_variants_are_distinct(self):
        pkgs = [
            self._pkg("python314Packages.xstatic-asciinema-player",
                      "xstatic-asciinema-player"),
            self._pkg("python313Packages.xstatic-asciinema-player",
                      "xstatic-asciinema-player"),
        ]
        assert len(deduplicate(pkgs)) == 2


class TestRealNixpkgsAdversarialRegression:
    """The real-world case that exposed the bug.

    Unlike the generic ``nx``/``nxXtend`` example, both attributes here exist
    in nixpkgs and are DIFFERENT packages:

        nix eval nixpkgs#agg.name            -> agg-2.5      (C library)
        nix eval nixpkgs#asciinema-agg.name  -> agg-1.9.0    (the intended one)

    A regression here does not fail loudly with an undefined variable — it
    silently installs the wrong package, which is why this case is pinned.
    """

    ADVERSARIAL_ATTR = "asciinema-agg"
    ADVERSARIAL_PNAME = "agg"

    def test_api_maps_attribute_not_pname(self):
        pkgs = search_module(
            "stable", [_api_hit(self.ADVERSARIAL_ATTR, self.ADVERSARIAL_PNAME)])
        assert pkgs[0].attribute == "asciinema-agg"
        assert pkgs[0].name == "agg"

    def test_reference_is_asciinema_agg_not_agg(self):
        ref = build_package_reference(
            self.ADVERSARIAL_ATTR, "stable", "explicit_pkgs")
        assert ref == "pkgs.asciinema-agg"
        assert ref != "pkgs.agg"

    def test_wrong_package_is_never_referenced(self):
        """The trap: pkgs.agg is valid Nix, so this must fail silently."""
        ref = build_package_reference(
            self.ADVERSARIAL_ATTR, "stable", "with_pkgs")
        assert ref != self.ADVERSARIAL_PNAME

    def test_installed_pname_package_does_not_satisfy_request(self):
        installed_agg = '''{ pkgs, ... }: {
  environment.systemPackages = with pkgs; [
    agg
  ];
}'''
        assert not is_package_exists(
            installed_agg, self.ADVERSARIAL_ATTR, TP, source="stable")

    def test_installed_pname_package_does_not_collide(self):
        installed_agg = '''{ pkgs, ... }: {
  environment.systemPackages = with pkgs; [
    agg
  ];
}'''
        assert not is_package_name_taken(installed_agg, self.ADVERSARIAL_ATTR, TP)

    def test_dedup_keeps_both_distinct_packages(self):
        pkgs = [
            Package(name="agg", version="2.5", description="d",
                    source="stable", type=None, attribute="agg"),
            Package(name="agg", version="1.9.0", description="d",
                    source="stable", type=None, attribute="asciinema-agg"),
        ]
        assert len(deduplicate(pkgs)) == 2
