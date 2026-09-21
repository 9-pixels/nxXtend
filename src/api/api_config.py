# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 9-pixels

# Search.nixos.org Elasticsearch backend configuration.
# These values are the same public credentials used by nh and other Nix tools.
# They are not user-specific secrets — they are the shared API key for the
# search.nixos.org backend.

STABLE_URL = "https://search.nixos.org/backend/latest-51-nixos-26.05/_search"
UNSTABLE_URL = "https://search.nixos.org/backend/latest-51-nixos-unstable/_search"

# Basic auth token for search.nixos.org Elasticsearch backend.
# This is a public credential (same one used by nh), not a user secret.
_API_TOKEN = "YVdWU0FMWHBadjpYOGdQSG56TDUyd0ZFZWt1eHNmUTljU2g="

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Basic {_API_TOKEN}",
}
