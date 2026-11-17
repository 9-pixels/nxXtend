# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 9-pixels

from api.api_config import STABLE_URL
from api.client import search
from models.package import Package

_SOURCE = "stable"


def stable_search(pkg_name: str) -> list[Package]:
    """Search for packages in the nixpkgs stable channel via nixos.org API."""
    return search(STABLE_URL, _SOURCE, pkg_name)
