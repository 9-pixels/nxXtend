# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 9-pixels

from api.errors import PackageSearchError, PackageSearchFailed
from api.stable import stable_search
from api.unstable import unstable_search

def deduplicate(packages):
    """Drop duplicate packages, keyed by Nix attribute identity.

    Keyed on ``attribute`` (package_attr_name) rather than ``name``: a
    package's upstream pname is not its attribute — the attribute
    ``nxXtend`` has pname ``nx`` — so deduplicating on pname would collapse
    distinct packages into one and hide the rest.
    """
    seen = set()
    result = []
    for pkg in packages:
        if pkg.attribute not in seen:
            seen.add(pkg.attribute)
            result.append(pkg)
    return result

def search(pkg_name: str):
    """Yield ``(source, packages)`` per channel, in order.

    A channel that cannot be searched is skipped rather than aborting the
    whole search, so the other channel's results still reach the user. Once
    the generator is exhausted, :class:`PackageSearchFailed` is raised if any
    channel failed, so the failure is reported without being silent.
    """
    failures = []
    for source, fetch in (("stable", stable_search), ("unstable", unstable_search)):
        try:
            packages = deduplicate(fetch(pkg_name))
        except PackageSearchError as exc:
            failures.append(exc)
            continue
        yield source, packages
    if failures:
        raise PackageSearchFailed(failures)
