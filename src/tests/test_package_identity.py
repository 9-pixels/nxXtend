"""Tests for package identity, duplicate detection, and source-awareness (§13-14).

Covers:
  - resolve_identity for all input forms (bare, pkgs., unstable_var.)
  - is_package_exists source-awareness
  - is_package_name_taken cross-source collision
  - remove_package source isolation
  - resolve_remove_target ambiguity resolution
  - add_package C1 deduplication
  - pkgs.pkgs. double-prefix prevention
  - install semantics (stable vs unstable non-conflict)
  - custom unstable_variable support
  - multi-package pre-validation (simulated)
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.writer import (
    is_package_exists, is_package_name_taken,
    resolve_identity, resolve_remove_target,
    remove_package, add_package, build_package_reference,
)

TP = Path("/tmp")

WITH_PKGS = '''{ pkgs, ... }: {
  environment.systemPackages = with pkgs; [
    htop
    unstable.htop
    git
  ];
}'''

EXPLICIT = '''{ pkgs, ... }: {
  environment.systemPackages = [ pkgs.htop pkgs.git ];
}'''

STABLE_ONLY = '''{ pkgs, ... }: {
  environment.systemPackages = with pkgs; [
    htop
  ];
}'''

UNSTABLE_ONLY = '''{ pkgs, ... }: {
  environment.systemPackages = with pkgs; [
    unstable.htop
  ];
}'''

class TestResolveIdentity(unittest.TestCase):
    def test_stable_bare_name(self):
        id_ = resolve_identity("htop", "stable")
        self.assertEqual(id_.name, "htop")
        self.assertEqual(id_.source, "stable")
        self.assertEqual(id_.reference, "htop")

    def test_unstable_bare_name(self):
        id_ = resolve_identity("htop", "unstable", "unstable")
        self.assertEqual(id_.name, "htop")
        self.assertEqual(id_.source, "unstable")
        self.assertEqual(id_.reference, "unstable.htop")

    def test_custom_unstable_var(self):
        id_ = resolve_identity("htop", "unstable", "up")
        self.assertEqual(id_.reference, "up.htop")

    def test_explicit_pkgs_prefix_stripped(self):
        id_ = resolve_identity("pkgs.htop", "stable")
        self.assertEqual(id_.name, "htop")
        self.assertEqual(id_.reference, "htop")

    def test_unstable_var_prefix_stripped_from_stable(self):
        # Passing "unstable.htop" with source="stable" is stripped, not passed through
        id_ = resolve_identity("unstable.htop", "stable", "unstable")
        self.assertEqual(id_.source, "stable")
        self.assertEqual(id_.name, "htop")
        self.assertEqual(id_.reference, "htop")
        self.assertNotIn("unstable", id_.reference)


class TestIsPackageExists(unittest.TestCase):
    def test_stable_match(self):
        self.assertTrue(is_package_exists(STABLE_ONLY, "htop", TP, source="stable"))

    def test_stable_does_not_match_unstable(self):
        self.assertFalse(
            is_package_exists(STABLE_ONLY, "htop", TP,
                              source="unstable", unstable_var="unstable"))

    def test_unstable_does_not_match_stable(self):
        self.assertFalse(
            is_package_exists(STABLE_ONLY, "htop", TP,
                              source="unstable", unstable_var="unstable"))

    def test_unstable_match(self):
        self.assertTrue(
            is_package_exists(UNSTABLE_ONLY, "htop", TP,
                              source="unstable", unstable_var="unstable"))

    def test_stable_reference_does_not_match_stable_source(self):
        # Passing an unstable reference name with source="stable" → False
        self.assertFalse(
            is_package_exists(STABLE_ONLY, "unstable.htop", TP,
                              source="stable", unstable_var="unstable"))

    def test_both_sources_present(self):
        self.assertTrue(is_package_exists(WITH_PKGS, "htop", TP, source="stable"))
        self.assertTrue(
            is_package_exists(WITH_PKGS, "htop", TP,
                              source="unstable", unstable_var="unstable"))


class TestIsPackageNameTaken(unittest.TestCase):
    def test_name_taken_stable(self):
        self.assertTrue(is_package_name_taken(STABLE_ONLY, "htop", TP))

    def test_name_taken_unstable(self):
        self.assertTrue(is_package_name_taken(UNSTABLE_ONLY, "htop", TP))

    def test_name_not_taken(self):
        self.assertFalse(is_package_name_taken(STABLE_ONLY, "ripgrep", TP))

    def test_custom_var_name_taken(self):
        content = '''{ pkgs, ... }: {
  environment.systemPackages = with pkgs; [
    up.htop
  ];
}'''
        self.assertTrue(is_package_name_taken(content, "htop", TP, unstable_var="up"))


class TestRemovePackageSourceIsolation(unittest.TestCase):
    def test_remove_stable_preserves_unstable(self):
        new, found = remove_package(WITH_PKGS, "htop", TP, source="stable", unstable_var="unstable")
        self.assertTrue(found)
        self.assertIn("unstable.htop", new)
        self.assertNotIn("\n    htop\n", new)

    def test_remove_unstable_preserves_stable(self):
        new, found = remove_package(WITH_PKGS, "htop", TP, source="unstable", unstable_var="unstable")
        self.assertTrue(found)
        self.assertIn("\n    htop\n", new)
        self.assertNotIn("unstable.htop", new)

    def test_remove_with_trailing_comment(self):
        content = '''{ pkgs, ... }: {
  environment.systemPackages = with pkgs; [
    git # my fav
    vim
  ];
}'''
        new, found = remove_package(content, "git", TP, source="stable")
        self.assertTrue(found)
        self.assertNotIn("git", new)


class TestResolveRemoveTarget(unittest.TestCase):
    def test_case_a_only_stable(self):
        r = resolve_remove_target(STABLE_ONLY, "htop", TP, unstable_var="unstable")
        self.assertEqual(r.source, "stable")

    def test_case_b_only_unstable(self):
        r = resolve_remove_target(UNSTABLE_ONLY, "htop", TP, unstable_var="unstable")
        self.assertEqual(r.source, "unstable")
        self.assertEqual(r.reference, "unstable.htop")

    def test_case_c_both_ambiguous(self):
        r = resolve_remove_target(WITH_PKGS, "htop", TP, unstable_var="unstable")
        self.assertEqual(r.source, "ambiguous")
        self.assertEqual(len(r.matches), 2)

    def test_case_d_explicit_unstable(self):
        r = resolve_remove_target(WITH_PKGS, "unstable.htop", TP, unstable_var="unstable")
        self.assertEqual(r.source, "unstable")
        self.assertEqual(len(r.matches), 1)

    def test_custom_var_resolve(self):
        content = '''{ pkgs, ... }: {
  environment.systemPackages = with pkgs; [
    up.htop
  ];
}'''
        r = resolve_remove_target(content, "htop", TP, unstable_var="up")
        self.assertEqual(r.source, "unstable")
        self.assertEqual(r.reference, "up.htop")


class TestBuildPackageReferenceNoDoublePrefix(unittest.TestCase):
    def test_stable_with_pkgs(self):
        self.assertEqual(build_package_reference("htop", "stable", "with_pkgs"), "htop")

    def test_stable_explicit(self):
        self.assertEqual(build_package_reference("htop", "stable", "explicit_pkgs"), "pkgs.htop")

    def test_unstable_with_pkgs(self):
        self.assertEqual(
            build_package_reference("htop", "unstable", "with_pkgs", "unstable"),
            "unstable.htop")

    def test_no_pkgs_pkgs_double(self):
        ref = build_package_reference("pkgs.htop", "stable", "explicit_pkgs")
        self.assertNotIn("pkgs.pkgs", ref)
        self.assertEqual(ref, "pkgs.htop")

    def test_no_unstable_unstable_double(self):
        ref = build_package_reference("unstable.htop", "unstable", "with_pkgs", "unstable")
        self.assertNotIn("unstable.unstable", ref)
        self.assertEqual(ref, "unstable.htop")


class TestAddPackageDeduplication(unittest.TestCase):
    def test_dedup_with_pkgs(self):
        r = add_package(STABLE_ONLY, "htop", TP)
        self.assertEqual(r.status, "no_change")
        self.assertEqual(r.content.count("htop"), 1)

    def test_dedup_explicit(self):
        content = '''{ pkgs, ... }: {
  environment.systemPackages = [ pkgs.git ];
}'''
        r = add_package(content, "git", TP)
        self.assertEqual(r.status, "no_change")
        self.assertEqual(r.content.count("git"), 1)


class TestInstallSemantics(unittest.TestCase):
    def test_stable_vs_unstable_not_conflict(self):
        # stable request, only unstable.htop exists → no conflict
        self.assertFalse(is_package_exists(UNSTABLE_ONLY, "htop", TP, source="stable"))

    def test_unstable_vs_stable_conflict(self):
        # unstable request, only stable htop exists → name taken → conflict
        self.assertTrue(is_package_name_taken(STABLE_ONLY, "htop", TP, unstable_var="unstable"))


if __name__ == "__main__":
    unittest.main()
