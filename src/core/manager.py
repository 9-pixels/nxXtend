# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 9-pixels

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
    stable = deduplicate(stable_search(pkg_name))
    yield "stable", stable
    unstable = deduplicate(unstable_search(pkg_name))
    yield "unstable", unstable

