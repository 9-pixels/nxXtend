# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 9-pixels

from api.errors import PackageSearchError, PackageSearchFailed
from api.stable import stable_search
from api.unstable import unstable_search
from models.package import Package


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


def resolve_packages(source: str, names: list[str]) -> tuple[list[Package], list[str]]:
    """Resolve each requested name to exactly one package in one source.

    Returns ``(resolved, missing)`` in the order the names were given.
    Duplicate names are collapsed. A name with no exact match is reported
    as missing; the caller must not fall back to another source and must
    not install a partial set.

    Matching is by canonical attribute first, then by upstream pname. The
    pname is only a lookup key — what gets installed is always the
    attribute. A hit count is never used as evidence that a package exists:
    the search backend answers a nonsense query with hundreds of fuzzy
    hits, so "there were results" does not mean "the package exists".

    Raises :class:`PackageSearchFailed` when the source cannot be searched
    at all, because a partial resolution cannot produce a complete install.
    """
    # Resolved at call time, not import time: the module-level names are the
    # seam tests patch, and a dict built at import would freeze over them.
    fetch = {"stable": stable_search, "unstable": unstable_search}[source]
    resolved: list[Package] = []
    missing: list[str] = []
    for name in dict.fromkeys(names):
        try:
            hits = deduplicate(fetch(name))
        except PackageSearchError as exc:
            raise PackageSearchFailed([exc]) from exc
        exact = [pkg for pkg in hits if pkg.attribute == name]
        if not exact:
            exact = [pkg for pkg in hits if pkg.name == name]
        if exact:
            resolved.append(exact[0])
        else:
            missing.append(name)
    return resolved, missing
