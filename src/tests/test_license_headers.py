"""License header guard.

The project is GPL-3.0-or-later and carries a per-file SPDX notice. These
modules had that notice before the error-reporting work; a rewrite that drops
it would silently weaken the license terms, so the header is pinned here.

Several other modules never carried one. They are deliberately not listed:
this guard exists to stop a regression on files that already comply, not to
re-litigate the files that do not.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HEADER = "# SPDX-License-Identifier: GPL-3.0-or-later"

FILES_WITH_HEADERS = (
    "src/api/api_config.py",
    "src/core/config.py",
    "src/core/manager.py",
    "src/core/target.py",
    "src/flakes/discovery.py",
    "src/flakes/executor.py",
    "src/flakes/resolver.py",
    "src/main.py",
    "src/ui/display.py",
    "src/ui/first_setup.py",
)


@pytest.mark.parametrize("rel_path", FILES_WITH_HEADERS)
def test_license_header_present(rel_path):
    content = (ROOT / rel_path).read_text()
    assert content.startswith(HEADER), f"{rel_path} lost its license header"
