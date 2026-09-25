# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 9-pixels

from api.stable import stable_search
from api.unstable import unstable_search

def deduplicate(packages):
    seen = set()
    result = []
    for pkg in packages:
        if pkg.name not in seen:
            seen.add(pkg.name)
            result.append(pkg)
    return result

def search(pkg_name: str):
    stable = deduplicate(stable_search(pkg_name))
    yield "stable", stable
    unstable = deduplicate(unstable_search(pkg_name))
    yield "unstable", unstable

