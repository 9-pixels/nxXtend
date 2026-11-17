# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 9-pixels

import requests

from api.api_config import HEADERS
from api.errors import PackageSearchError
from models.package import Package

# A search that hangs is worse than a search that fails: without a timeout
# `requests` waits indefinitely and `nx install` never returns.
REQUEST_TIMEOUT = 15

# Fields requested from the search backend. `package_attr_name` is the
# canonical Nix identity; the rest are display metadata.
_FIELDS = ["package_attr_name", "package_pname", "package_description"]


def describe_request_error(exc: requests.exceptions.RequestException) -> str:
    """Translate a requests exception into something a user can act on."""
    if isinstance(exc, requests.exceptions.Timeout):
        return f"the search service did not answer within {REQUEST_TIMEOUT}s"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "could not reach the search service — check your network connection"
    if isinstance(exc, requests.exceptions.HTTPError):
        status = getattr(exc.response, "status_code", None)
        if status is not None:
            return f"the search service responded with HTTP {status}"
        return "the search service rejected the request"
    return str(exc) or type(exc).__name__


def search(url: str, source: str, pkg_name: str) -> list[Package]:
    """Query one search.nixos.org channel and map its hits to packages.

    Raises :class:`PackageSearchError` with a user-readable reason instead of
    letting a network or parsing failure escape as a traceback.
    """
    payload = {
        "query": {"multi_match": {"query": pkg_name, "fields": _FIELDS}},
        "size": 500,
    }
    try:
        response = requests.post(url, headers=HEADERS, json=payload,
                                 timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise PackageSearchError(source, describe_request_error(exc)) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise PackageSearchError(
            source, "the search service returned an unreadable response"
        ) from exc

    try:
        hits = data["hits"]["hits"]
    except (KeyError, TypeError) as exc:
        raise PackageSearchError(
            source, "the search service returned an unexpected response shape"
        ) from exc

    packages = []
    for hit in hits:
        record = hit.get("_source") if isinstance(hit, dict) else None
        if not isinstance(record, dict):
            continue
        attribute = record.get("package_attr_name")
        if not attribute:
            # Without the canonical attribute there is no valid Nix
            # reference, so the record is dropped rather than falling back
            # to the upstream pname (which is a different identity).
            continue
        packages.append(Package(
            name=record.get("package_pname") or attribute,
            version=record.get("package_pversion"),
            description=record.get("package_description"),
            source=source,
            type=None,
            attribute=attribute,
        ))
    return packages
