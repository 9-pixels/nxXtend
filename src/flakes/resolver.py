# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 9-pixels

import json
import subprocess

from flakes.models import FlakeSource
from ui.display import show_command_error, show_error, timeout_detail

_METADATA_TIMEOUT = 60


def parse_flake_url(url: str) -> FlakeSource:
    if "#" in url:
        base, target = url.split("#", 1)
        return FlakeSource(url=base, target=target)
    return FlakeSource(url=url)


def get_metadata(source: FlakeSource) -> FlakeSource:
    """Resolve a flake reference to its metadata.

    Returns the source unchanged when the reference cannot be resolved, so
    callers can still attempt discovery. A timeout is reported rather than
    allowed to escape, and the return contract is preserved either way.
    """
    cmd = ["nix", "flake", "metadata", "--json", source.url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=_METADATA_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        show_error(
            f"nix flake metadata timed out after {_METADATA_TIMEOUT}s for "
            f"{source.url}",
            timeout_detail(exc, _METADATA_TIMEOUT),
        )
        return source
    if result.returncode != 0 or not result.stdout.strip():
        show_command_error(cmd, result)
        return source
    data = json.loads(result.stdout)
    locked = data.get("locked") or {}
    revision = locked.get("rev")
    return FlakeSource(url=source.url, target=source.target, revision=revision)
