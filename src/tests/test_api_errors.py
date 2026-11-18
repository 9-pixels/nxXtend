"""Package search failure handling.

`nx install` used to start with a bare `requests.post`: no timeout, no status
check, no response-shape check. A network hiccup, a slow host, an unreadable
body or an unexpected JSON shape all escaped as a Python traceback — on the
most common command in the tool.

These tests pin the contract: every failure becomes a
:class:`api.errors.PackageSearchError` with a user-readable reason and the
original exception chained; a source that cannot be searched raises
:class:`PackageSearchFailed` instead of yielding a partial result; and
``handle_install`` reports instead of crashing.
"""
import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from api.client import REQUEST_TIMEOUT, search
from api.errors import PackageSearchError, PackageSearchFailed
from core.manager import resolve_packages
from models.package import Package

import main as main_mod


SYS = '{  environment.systemPackages = with pkgs; [\n    git\n  ];\n}'

HITS = {"hits": {"hits": [{"_source": {
    "package_attr_name": "vim", "package_pname": "vim",
    "package_pversion": "9.0", "package_description": "editor"}}]}}


def _response(json_data=None, status_code=200, json_side_effect=None):
    resp = MagicMock()
    resp.status_code = status_code
    if json_side_effect is not None:
        resp.json.side_effect = json_side_effect
    else:
        resp.json.return_value = json_data
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=resp)
    return resp


# ── request failures ────────────────────────────────────────────────────────

@pytest.mark.parametrize("exc,expected", [
    (requests.exceptions.ConnectionError("no route to host"),
     "could not reach the search service"),
    (requests.exceptions.Timeout("timed out"),
     "did not answer within"),
    (requests.exceptions.HTTPError(response=_response(status_code=503)),
     "HTTP 503"),
], ids=["connection", "timeout", "http-503"])
def test_request_failure_becomes_a_controlled_error(exc, expected):
    with patch("api.client.requests.post", side_effect=exc):
        with pytest.raises(PackageSearchError) as info:
            search("https://x", "stable", "vim")
    assert info.value.source == "stable"
    assert expected in info.value.reason
    assert info.value.__cause__ is exc, "the original exception must be chained"


def test_the_request_carries_a_timeout():
    """Without a timeout a hung host would hang `nx install` forever."""
    with patch("api.client.requests.post", return_value=_response(HITS)) as post:
        search("https://x", "stable", "vim")
    assert post.call_args[1]["timeout"] == REQUEST_TIMEOUT


# ── response failures ───────────────────────────────────────────────────────

def test_unreadable_json_is_reported():
    with patch("api.client.requests.post",
               return_value=_response(json_side_effect=ValueError("no json"))):
        with pytest.raises(PackageSearchError) as info:
            search("https://x", "stable", "vim")
    assert "unreadable" in info.value.reason


@pytest.mark.parametrize("payload", [
    {}, {"hits": {}}, {"hits": "nope"}, "not-a-dict", None,
], ids=["empty", "no-hits", "hits-not-dict", "top-level-list", "null"])
def test_unexpected_shape_is_reported(payload):
    with patch("api.client.requests.post", return_value=_response(payload)):
        with pytest.raises(PackageSearchError) as info:
            search("https://x", "unstable", "vim")
    assert "unexpected response shape" in info.value.reason
    assert info.value.source == "unstable"


def test_records_without_an_attribute_are_skipped():
    hits = {"hits": {"hits": [
        {"_source": {"package_pname": "vim"}},
        {"_source": {"package_attr_name": "", "package_pname": "x"}},
        {"_source": {"package_attr_name": "vim", "package_pname": "vim"}},
        "not-a-dict",
    ]}}
    with patch("api.client.requests.post", return_value=_response(hits)):
        packages = search("https://x", "stable", "vim")
    assert [p.attribute for p in packages] == ["vim"]


def test_missing_metadata_does_not_crash():
    """A hit with an identity but no display metadata is still usable."""
    hits = {"hits": {"hits": [{"_source": {"package_attr_name": "vim"}}]}}
    with patch("api.client.requests.post", return_value=_response(hits)):
        packages = search("https://x", "stable", "vim")
    assert packages[0].attribute == "vim"
    assert packages[0].name == "vim"


# ── manager resolution ───────────────────────────────────────────────────────

def test_resolve_packages_raises_when_the_source_fails():
    with patch("core.manager.stable_search",
               side_effect=PackageSearchError("stable", "down")):
        with pytest.raises(PackageSearchFailed) as info:
            resolve_packages("stable", ["vim"])
    assert [e.source for e in info.value.errors] == ["stable"]
    assert "could not search stable" in info.value.detail


def test_resolve_packages_does_not_fall_back_to_the_other_source():
    """A name absent from the chosen source is missing, never rescued."""
    pkg = Package(name="vim", version="9.0", description="d",
                  source="unstable", type=None, attribute="vim")
    with patch("core.manager.stable_search", return_value=[]), \
         patch("core.manager.unstable_search", return_value=[pkg]) as un:
        resolved, missing = resolve_packages("stable", ["vim"])
    assert resolved == [] and missing == ["vim"]
    un.assert_not_called()


# ── the caller ──────────────────────────────────────────────────────────────

def test_handle_install_reports_a_total_search_failure(tmp_path):
    """No traceback: the failure is reported and the command stops cleanly."""
    config_nix = tmp_path / "configuration.nix"
    config_nix.write_text(SYS)
    config = {"setup": {"configuration_path": str(config_nix),
                        "flake_enabled": False,
                        "home_manager_enabled": False,
                        "unstable_variable": "unstable"}}

    failure = PackageSearchFailed([
        PackageSearchError("stable", "could not reach the search service"),
    ])
    buf = io.StringIO()
    with patch("main.show_source_select", return_value=1), \
         patch("main.resolve_packages", side_effect=failure), \
         redirect_stdout(buf):
        main_mod.handle_install(["vim"], config)

    out = buf.getvalue()
    assert "could not search stable" in out
    assert "Traceback (most recent call last)" not in out
