import json
from unittest.mock import patch, MagicMock


from flakes.resolver import get_metadata
from flakes.models import FlakeSource


def make_mock_run(returncode, stdout):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = ""
    return result


def test_metadata_success_with_locked_rev():
    """metadata successful with locked.rev"""
    mock_data = {
        "locked": {"rev": "abc123def456", "narHash": "sha256-xxx"},
        "original": {"owner": "NixOS", "repo": "nixpkgs", "type": "github"}
    }
    source = FlakeSource(url="github:NixOS/nixpkgs", target=None)

    with patch("flakes.resolver.subprocess.run") as mock_run:
        mock_run.return_value = make_mock_run(0, json.dumps(mock_data))
        result = get_metadata(source)

    assert result.revision == "abc123def456"
    assert result.url == "github:NixOS/nixpkgs"
    assert result.target is None


def test_metadata_locked_is_none():
    """locked = None (flake without lock file)"""
    mock_data = {"locked": None, "original": {"owner": "test"}}
    source = FlakeSource(url="github:test/no-lock", target=None)

    with patch("flakes.resolver.subprocess.run") as mock_run:
        mock_run.return_value = make_mock_run(0, json.dumps(mock_data))
        result = get_metadata(source)

    assert result.revision is None
    assert result.url == "github:test/no-lock"


def test_metadata_command_fails():
    """nix flake metadata command failed"""
    source = FlakeSource(url="github:nonexistent/repo", target="packages.x86_64-linux.foo")

    with patch("flakes.resolver.subprocess.run") as mock_run:
        mock_run.return_value = make_mock_run(1, "")
        result = get_metadata(source)

    # Should return the original source without change
    assert result.url == "github:nonexistent/repo"
    assert result.target == "packages.x86_64-linux.foo"
    assert result.revision is None


def test_metadata_preserves_target():
    """Preserving target from parse_flake_url"""
    mock_data = {"locked": {"rev": "xyz789"}}
    source = FlakeSource(url="github:NixOS/nixpkgs", target="packages.x86_64-linux.hello")

    with patch("flakes.resolver.subprocess.run") as mock_run:
        mock_run.return_value = make_mock_run(0, json.dumps(mock_data))
        result = get_metadata(source)

    assert result.target == "packages.x86_64-linux.hello"
    assert result.revision == "xyz789"


def test_metadata_empty_response():
    """Empty stdout response"""
    source = FlakeSource(url="github:test/repo")

    with patch("flakes.resolver.subprocess.run") as mock_run:
        mock_run.return_value = make_mock_run(0, "")
        result = get_metadata(source)

    assert result.revision is None
    assert result.url == "github:test/repo"


# ── Runner ─────────────────────────────────────────────────────────────────────
