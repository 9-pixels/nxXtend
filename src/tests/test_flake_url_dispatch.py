"""Unit tests for Flake URL dispatch in nx CLI.

These tests verify that the CLI correctly routes different Flake reference
formats to handle_flakes_install(), while preserving the behavior of known
subcommands (remove, upgrade, update, install) and short flags.

All tests are isolated from the network — they mock handle_flakes_install
and verify dispatch only.
"""
import sys
import os
import io
from unittest.mock import patch, MagicMock
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

import main as m
from core.target import Target

CONFIG = {"setup": {
    "configuration_path": "/tmp/…/configuration.nix",
    "flake_enabled": True,
    "flake_path": "/tmp/…/flake.nix",
    "home_manager_enabled": True,
    "home_manager_path": "/tmp/…/home.nix",
}}


def run_cli(argv):
    """Run main() with all handlers + subprocess mocked.

    Returns (exit_code_or_None, handler_calls) where handler_calls is a list
    of (handler_name, args, kwargs). SystemExit is captured.
    """
    calls = []
    def rec(name):
        def f(*a, **k):
            calls.append((name, a, k))
        return f
    try:
        with patch("main.handle_install", side_effect=rec("install")), \
             patch("main.handle_remove", side_effect=rec("remove")), \
             patch("main.handle_upgrade", side_effect=rec("upgrade")), \
             patch("main.handle_flakes_install", side_effect=rec("flakes_install")), \
             patch("main.handle_flakes_remove", side_effect=rec("flakes_remove")), \
             patch("main.handle_flakes_upgrade", side_effect=rec("flakes_upgrade")), \
             patch("main.subprocess.run") as mock_sub, \
             patch("main.bootstrap", return_value=CONFIG), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            mock_sub.return_value = MagicMock(returncode=0)
            sys.argv = argv
            m.main()
    except SystemExit as e:
        return e.code, calls
    return None, calls


# ── Test: known URL prefixes ───────────────────────────────────────────────

def test_github_url():
    code, calls = run_cli(["nx", "-f", "github:owner/repo"])
    assert calls == [("flakes_install", ("github:owner/repo", CONFIG), {"requested": None})]


def test_git_https_url():
    code, calls = run_cli(["nx", "-f", "git+https://host/owner/repo"])
    assert calls == [("flakes_install", ("git+https://host/owner/repo", CONFIG), {"requested": None})]


def test_git_ssh_url():
    code, calls = run_cli(["nx", "-f", "git+ssh://host/owner/repo"])
    assert calls == [("flakes_install", ("git+ssh://host/owner/repo", CONFIG), {"requested": None})]


def test_git_protocol_url():
    code, calls = run_cli(["nx", "-f", "git://host/owner/repo"])
    assert calls == [("flakes_install", ("git://host/owner/repo", CONFIG), {"requested": None})]


def test_git_file_url():
    code, calls = run_cli(["nx", "-f", "git+file:///path/to/repo"])
    assert calls == [("flakes_install", ("git+file:///path/to/repo", CONFIG), {"requested": None})]


def test_git_http_url():
    code, calls = run_cli(["nx", "-f", "git+http://host/repo"])
    assert calls == [("flakes_install", ("git+http://host/repo", CONFIG), {"requested": None})]


def test_git_git_url():
    code, calls = run_cli(["nx", "-f", "git+git://host/repo"])
    assert calls == [("flakes_install", ("git+git://host/repo", CONFIG), {"requested": None})]


def test_gitlab_url():
    code, calls = run_cli(["nx", "-f", "gitlab:owner/repo"])
    assert calls == [("flakes_install", ("gitlab:owner/repo", CONFIG), {"requested": None})]


def test_sourcehut_url():
    code, calls = run_cli(["nx", "-f", "sourcehut:~user/repo"])
    assert calls == [("flakes_install", ("sourcehut:~user/repo", CONFIG), {"requested": None})]


def test_hg_https_url():
    code, calls = run_cli(["nx", "-f", "hg+https://host/repo"])
    assert calls == [("flakes_install", ("hg+https://host/repo", CONFIG), {"requested": None})]


def test_hg_ssh_url():
    code, calls = run_cli(["nx", "-f", "hg+ssh://host/repo"])
    assert calls == [("flakes_install", ("hg+ssh://host/repo", CONFIG), {"requested": None})]


def test_hg_file_url():
    code, calls = run_cli(["nx", "-f", "hg+file:///path"])
    assert calls == [("flakes_install", ("hg+file:///path", CONFIG), {"requested": None})]


def test_hg_http_url():
    code, calls = run_cli(["nx", "-f", "hg+http://host/repo"])
    assert calls == [("flakes_install", ("hg+http://host/repo", CONFIG), {"requested": None})]


def test_tarball_https_url():
    code, calls = run_cli(["nx", "-f", "tarball+https://host/file.tar.gz"])
    assert calls == [("flakes_install", ("tarball+https://host/file.tar.gz", CONFIG), {"requested": None})]


def test_tarball_http_url():
    code, calls = run_cli(["nx", "-f", "tarball+http://host/file.tar.gz"])
    assert calls == [("flakes_install", ("tarball+http://host/file.tar.gz", CONFIG), {"requested": None})]


def test_tarball_file_url():
    code, calls = run_cli(["nx", "-f", "tarball+file:///path"])
    assert calls == [("flakes_install", ("tarball+file:///path", CONFIG), {"requested": None})]


def test_file_https_url():
    code, calls = run_cli(["nx", "-f", "file+https://host/file"])
    assert calls == [("flakes_install", ("file+https://host/file", CONFIG), {"requested": None})]


def test_file_http_url():
    code, calls = run_cli(["nx", "-f", "file+http://host/file"])
    assert calls == [("flakes_install", ("file+http://host/file", CONFIG), {"requested": None})]


def test_file_file_url():
    code, calls = run_cli(["nx", "-f", "file+file:///path"])
    assert calls == [("flakes_install", ("file+file:///path", CONFIG), {"requested": None})]


def test_http_url():
    code, calls = run_cli(["nx", "-f", "http://host/file.tar.gz"])
    assert calls == [("flakes_install", ("http://host/file.tar.gz", CONFIG), {"requested": None})]


def test_https_url():
    code, calls = run_cli(["nx", "-f", "https://host/file.tar.gz"])
    assert calls == [("flakes_install", ("https://host/file.tar.gz", CONFIG), {"requested": None})]


# ── Test: local paths ──────────────────────────────────────────────────────

def test_path_prefix():
    code, calls = run_cli(["nx", "-f", "path:/absolute/path"])
    assert calls == [("flakes_install", ("path:/absolute/path", CONFIG), {"requested": None})]


def test_absolute_path():
    code, calls = run_cli(["nx", "-f", "/absolute/path"])
    assert calls == [("flakes_install", ("/absolute/path", CONFIG), {"requested": None})]


def test_relative_path_dot():
    code, calls = run_cli(["nx", "-f", "./relative/path"])
    assert calls == [("flakes_install", ("./relative/path", CONFIG), {"requested": None})]


def test_relative_path_dotdot():
    code, calls = run_cli(["nx", "-f", "../relative/path"])
    assert calls == [("flakes_install", ("../relative/path", CONFIG), {"requested": None})]


# ── Test: Flake Registry references ────────────────────────────────────────

def test_registry_nixpkgs():
    code, calls = run_cli(["nx", "-f", "nixpkgs"])
    assert calls == [("flakes_install", ("nixpkgs", CONFIG), {"requested": None})]


def test_registry_nixpkgs_channel():
    code, calls = run_cli(["nx", "-f", "nixpkgs/nixos-unstable"])
    assert calls == [("flakes_install", ("nixpkgs/nixos-unstable", CONFIG), {"requested": None})]


# ── Test: URL parameters and fragments ─────────────────────────────────────

def test_url_with_ref_param():
    code, calls = run_cli(["nx", "-f", "git+https://host/repo?ref=main"])
    assert calls == [("flakes_install", ("git+https://host/repo?ref=main", CONFIG), {"requested": None})]


def test_url_with_dir_param():
    code, calls = run_cli(["nx", "-f", "git+https://host/repo?dir=subdir"])
    assert calls == [("flakes_install", ("git+https://host/repo?dir=subdir", CONFIG), {"requested": None})]


def test_url_with_target_fragment():
    code, calls = run_cli(["nx", "-f", "git+https://host/repo#packages.x86_64-linux.default"])
    assert calls == [("flakes_install", ("git+https://host/repo#packages.x86_64-linux.default", CONFIG), {"requested": None})]


def test_github_with_target_fragment():
    code, calls = run_cli(["nx", "-f", "github:owner/repo#packages.x86_64-linux.default"])
    assert calls == [("flakes_install", ("github:owner/repo#packages.x86_64-linux.default", CONFIG), {"requested": None})]


# ── Test: known subcommands preserved ───────────────────────────────────────

def test_flakes_remove():
    code, calls = run_cli(["nx", "flakes", "remove", "myflake"])
    assert calls == [("flakes_remove", ("myflake", CONFIG), {"requested": None})]


def test_flakes_upgrade():
    code, calls = run_cli(["nx", "flakes", "upgrade"])
    assert calls == [("flakes_upgrade", (CONFIG,), {})]


def test_flakes_update():
    code, calls = run_cli(["nx", "flakes", "update"])
    assert calls == [("flakes_upgrade", (CONFIG,), {})]


def test_flakes_install_explicit():
    code, calls = run_cli(["nx", "flakes", "install", "github:owner/repo"])
    assert calls == [("flakes_install", ("github:owner/repo", CONFIG), {"requested": None})]


def test_flakes_install_git_url():
    code, calls = run_cli(["nx", "flakes", "install", "git+https://host/owner/repo"])
    assert calls == [("flakes_install", ("git+https://host/owner/repo", CONFIG), {"requested": None})]


# ── Test: short flags preserved ────────────────────────────────────────────

def test_short_install():
    code, calls = run_cli(["nx", "-i", "firefox"])
    assert calls == [("install", ("firefox", CONFIG), {"requested": None})]


def test_short_remove():
    code, calls = run_cli(["nx", "-r", "firefox"])
    assert calls == [("remove", ("firefox", CONFIG), {"requested": None})]


def test_short_upgrade():
    code, calls = run_cli(["nx", "-u"])
    assert calls == [("upgrade", (CONFIG,), {})]


def test_short_flake_install():
    code, calls = run_cli(["nx", "-f", "github:owner/repo"])
    assert calls == [("flakes_install", ("github:owner/repo", CONFIG), {"requested": None})]


def test_short_flake_install_explicit():
    code, calls = run_cli(["nx", "-f", "-i", "github:owner/repo"])
    assert calls == [("flakes_install", ("github:owner/repo", CONFIG), {"requested": None})]


def test_short_flake_remove():
    code, calls = run_cli(["nx", "-f", "-r", "myflake"])
    assert calls == [("flakes_remove", ("myflake", CONFIG), {"requested": None})]


def test_short_flake_upgrade():
    code, calls = run_cli(["nx", "-f", "-u"])
    assert calls == [("flakes_upgrade", (CONFIG,), {})]


# ── Test: -H flag with various sources ─────────────────────────────────────

def test_home_flag_with_github():
    code, calls = run_cli(["nx", "-f", "-H", "github:owner/repo"])
    assert calls == [("flakes_install", ("github:owner/repo", CONFIG), {"requested": Target.HOME})]


def test_home_flag_with_git_url():
    code, calls = run_cli(["nx", "-f", "-H", "git+https://host/owner/repo"])
    assert calls == [("flakes_install", ("git+https://host/owner/repo", CONFIG), {"requested": Target.HOME})]


def test_home_flag_before_f():
    code, calls = run_cli(["nx", "-H", "-f", "git+https://host/owner/repo"])
    assert calls == [("flakes_install", ("git+https://host/owner/repo", CONFIG), {"requested": Target.HOME})]


# ── Test: no argument → print_help ─────────────────────────────────────────

def test_flakes_no_args():
    code, calls = run_cli(["nx", "flakes"])
    assert calls == []


def test_no_args():
    code, calls = run_cli(["nx"])
    assert calls == []


# ── Test: unknown subcommand without name → print_help ─────────────────────

def test_flakes_remove_no_name():
    code, calls = run_cli(["nx", "flakes", "remove"])
    assert calls == []


def test_flakes_install_no_name():
    code, calls = run_cli(["nx", "flakes", "install"])
    assert calls == []


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
