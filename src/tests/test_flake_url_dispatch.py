"""Unit tests for Flake URL dispatch in nx CLI.

These tests verify that the CLI correctly routes different Flake reference
formats to handle_flakes_install(), while preserving the behavior of known
subcommands (remove, upgrade, update, install) and short flags.

All tests are isolated from the network — they mock handle_flakes_install
and verify dispatch only.
"""
import pytest

from core.target import Target


# ── Flake reference formats → handle_flakes_install ─────────────────────────

@pytest.mark.parametrize("url", [
    "github:owner/repo",
    "gitlab:owner/repo",
    "sourcehut:~user/repo",
], ids=["github", "gitlab", "sourcehut"])
def test_forge_shortcut_urls(url, run_cli, cli_config):
    _, calls, _ = run_cli(["nx", "-f", url])
    assert calls == [("flakes_install", (url, cli_config), {"requested": None})]


@pytest.mark.parametrize("url", [
    "git+https://host/owner/repo",
    "git+ssh://host/owner/repo",
    "git://host/owner/repo",
    "git+file:///path/to/repo",
    "git+http://host/repo",
    "git+git://host/repo",
], ids=["git+https", "git+ssh", "git", "git+file", "git+http", "git+git"])
def test_git_urls(url, run_cli, cli_config):
    _, calls, _ = run_cli(["nx", "-f", url])
    assert calls == [("flakes_install", (url, cli_config), {"requested": None})]


@pytest.mark.parametrize("url", [
    "hg+https://host/repo",
    "hg+ssh://host/repo",
    "hg+file:///path",
    "hg+http://host/repo",
], ids=["hg+https", "hg+ssh", "hg+file", "hg+http"])
def test_mercurial_urls(url, run_cli, cli_config):
    _, calls, _ = run_cli(["nx", "-f", url])
    assert calls == [("flakes_install", (url, cli_config), {"requested": None})]


@pytest.mark.parametrize("url", [
    "tarball+https://host/file.tar.gz",
    "tarball+http://host/file.tar.gz",
    "tarball+file:///path",
    "file+https://host/file",
    "file+http://host/file",
    "file+file:///path",
    "http://host/file.tar.gz",
    "https://host/file.tar.gz",
], ids=[
    "tarball+https", "tarball+http", "tarball+file",
    "file+https", "file+http", "file+file",
    "http", "https",
])
def test_archive_and_file_urls(url, run_cli, cli_config):
    _, calls, _ = run_cli(["nx", "-f", url])
    assert calls == [("flakes_install", (url, cli_config), {"requested": None})]


@pytest.mark.parametrize("url", [
    "path:/absolute/path",
    "/absolute/path",
    "./relative/path",
    "../relative/path",
], ids=["path:", "absolute", "./relative", "../relative"])
def test_local_paths(url, run_cli, cli_config):
    _, calls, _ = run_cli(["nx", "-f", url])
    assert calls == [("flakes_install", (url, cli_config), {"requested": None})]


@pytest.mark.parametrize("url", [
    "nixpkgs",
    "nixpkgs/nixos-unstable",
], ids=["nixpkgs", "nixpkgs channel"])
def test_registry_references(url, run_cli, cli_config):
    _, calls, _ = run_cli(["nx", "-f", url])
    assert calls == [("flakes_install", (url, cli_config), {"requested": None})]


@pytest.mark.parametrize("url", [
    "git+https://host/repo?ref=main",
    "git+https://host/repo?dir=subdir",
    "git+https://host/repo#packages.x86_64-linux.default",
    "github:owner/repo#packages.x86_64-linux.default",
], ids=["?ref=", "?dir=", "#target (git)", "#target (github)"])
def test_url_parameters_and_fragments(url, run_cli, cli_config):
    _, calls, _ = run_cli(["nx", "-f", url])
    assert calls == [("flakes_install", (url, cli_config), {"requested": None})]


# ── Known subcommands preserved ─────────────────────────────────────────────

def test_flakes_remove(run_cli, cli_config):
    _, calls, _ = run_cli(["nx", "flakes", "remove", "myflake"])
    assert calls == [("flakes_remove", ("myflake", cli_config), {"requested": None})]


@pytest.mark.parametrize("argv", [
    ["nx", "flakes", "upgrade"],
    ["nx", "flakes", "update"],
], ids=["upgrade", "update (alias)"])
def test_flakes_upgrade_and_update(argv, run_cli, cli_config):
    _, calls, _ = run_cli(argv)
    assert calls == [("flakes_upgrade", (cli_config,), {})]


@pytest.mark.parametrize("url", [
    "github:owner/repo",
    "git+https://host/owner/repo",
], ids=["github", "git+https"])
def test_flakes_install_explicit_form(url, run_cli, cli_config):
    _, calls, _ = run_cli(["nx", "flakes", "install", url])
    assert calls == [("flakes_install", (url, cli_config), {"requested": None})]


# ── Short flags preserved ───────────────────────────────────────────────────

@pytest.mark.parametrize("argv,op,name", [
    (["nx", "-i", "firefox"], "install", ["firefox"]),
    (["nx", "-r", "firefox"], "remove", "firefox"),
], ids=["-i", "-r"])
def test_short_install_and_remove(argv, op, name, run_cli, cli_config):
    _, calls, _ = run_cli(argv)
    assert calls == [(op, (name, cli_config), {"requested": None})]


def test_short_upgrade(run_cli, cli_config):
    _, calls, _ = run_cli(["nx", "-u"])
    assert calls == [("upgrade", (cli_config,), {})]


@pytest.mark.parametrize("argv,op,name", [
    (["nx", "-f", "github:owner/repo"], "flakes_install", "github:owner/repo"),
    (["nx", "-f", "-i", "github:owner/repo"], "flakes_install", "github:owner/repo"),
    (["nx", "-f", "-r", "myflake"], "flakes_remove", "myflake"),
], ids=["-f <url>", "-f -i <url>", "-f -r <name>"])
def test_short_flake_operations(argv, op, name, run_cli, cli_config):
    _, calls, _ = run_cli(argv)
    assert calls == [(op, (name, cli_config), {"requested": None})]


def test_short_flake_upgrade(run_cli, cli_config):
    _, calls, _ = run_cli(["nx", "-f", "-u"])
    assert calls == [("flakes_upgrade", (cli_config,), {})]


# ── -H flag with various sources ────────────────────────────────────────────

@pytest.mark.parametrize("argv", [
    ["nx", "-f", "-H", "github:owner/repo"],
    ["nx", "-f", "-H", "git+https://host/owner/repo"],
    ["nx", "-H", "-f", "git+https://host/owner/repo"],
], ids=["-f -H <url>", "-f -H <git-url>", "-H -f <git-url>"])
def test_home_flag_routes_to_home(argv, run_cli, cli_config):
    url = argv[-1]
    _, calls, _ = run_cli(argv)
    assert calls == [("flakes_install", (url, cli_config), {"requested": Target.HOME})]


# ── No argument → print_help ────────────────────────────────────────────────

@pytest.mark.parametrize("argv", [
    ["nx", "flakes"],
    ["nx"],
    ["nx", "flakes", "remove"],
    ["nx", "flakes", "install"],
], ids=[
    "flakes (no args)",
    "no args at all",
    "flakes remove without name",
    "flakes install without url",
])
def test_missing_argument_prints_help(argv, run_cli):
    _, calls, _ = run_cli(argv)
    assert calls == []
