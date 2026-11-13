"""CLI composition & validation tests.

All tests mock handlers and subprocess — no real nixos-rebuild, no real
nix flake update, no file changes. Verifies:
  - short forms -i/-r/-u/-f and compositions
  - -f defaults to install
  - long-form compatibility (incl. 'flakes install')
  - -H placement flexibility
  - invalid combinations rejected (exit 2)
  - upgrade -H / flakes upgrade -H / flakes update -H rejected BEFORE
    any external command runs (exit 1)

Migrated from the original script harness; every ``check`` maps 1:1 to a
collected pytest test instance.
"""
import pytest

from core.target import Target


# ── [1] Short commands reach the canonical handlers ─────────────────────────

@pytest.mark.parametrize("argv,op,name", [
    (["nx", "-i", "firefox"], "install", "firefox"),
    (["nx", "-r", "firefox"], "remove", "firefox"),
], ids=[
    "-i firefox → handle_install(firefox)",
    "-r firefox → handle_remove(firefox)",
])
def test_short_commands_reach_canonical_handlers(argv, op, name, run_cli, cli_config):
    _, calls, _ = run_cli(argv)
    assert calls == [(op, (name, cli_config), {"requested": None})]


def test_short_upgrade_reaches_handler(run_cli, cli_config):
    _, calls, _ = run_cli(["nx", "-u"])
    assert calls == [("upgrade", (cli_config,), {})]


# ── [2] -f compositions ────────────────────────────────────────────────────

@pytest.mark.parametrize("argv,op,name", [
    (["nx", "-f", "github:user/repo"], "flakes_install", "github:user/repo"),
    (["nx", "-f", "-i", "github:user/repo"], "flakes_install", "github:user/repo"),
    (["nx", "-f", "-r", "github:user/repo"], "flakes_remove", "github:user/repo"),
], ids=[
    "-f <url> → handle_flakes_install(url) (default install)",
    "-f -i <url> → handle_flakes_install(url) (explicit install)",
    "-f -r <name> → handle_flakes_remove(name)",
])
def test_flake_flag_compositions(argv, op, name, run_cli, cli_config):
    _, calls, _ = run_cli(argv)
    assert calls == [(op, (name, cli_config), {"requested": None})]


def test_flake_upgrade_short_flag(run_cli, cli_config):
    _, calls, _ = run_cli(["nx", "-f", "-u"])
    assert calls == [("flakes_upgrade", (cli_config,), {})]


# ── [3] Long-form compatibility ─────────────────────────────────────────────

@pytest.mark.parametrize("argv,op", [
    (["nx", "install", "firefox"], "install"),
    (["nx", "remove", "firefox"], "remove"),
    (["nx", "upgrade"], "upgrade"),
    (["nx", "flakes", "github:user/repo"], "flakes_install"),
    (["nx", "flakes", "remove", "x"], "flakes_remove"),
    (["nx", "flakes", "upgrade"], "flakes_upgrade"),
    (["nx", "flakes", "update"], "flakes_upgrade"),
], ids=[
    "install firefox → handle_install",
    "remove firefox → handle_remove",
    "upgrade → handle_upgrade",
    "flakes <url> → handle_flakes_install",
    "flakes remove x → handle_flakes_remove",
    "flakes upgrade → handle_flakes_upgrade",
    "flakes update → handle_flakes_upgrade (alias)",
])
def test_long_forms_reach_canonical_handlers(argv, op, run_cli):
    _, calls, _ = run_cli(argv)
    assert calls[0][0] == op


def test_flakes_install_explicit_form(run_cli, cli_config):
    _, calls, _ = run_cli(["nx", "flakes", "install", "github:user/repo"])
    assert calls == [("flakes_install", ("github:user/repo", cli_config), {"requested": None})]


# ── [4] -H composition ──────────────────────────────────────────────────────

@pytest.mark.parametrize("argv,op,name", [
    (["nx", "-i", "-H", "firefox"], "install", "firefox"),
    (["nx", "-r", "-H", "firefox"], "remove", "firefox"),
    (["nx", "-f", "-H", "github:user/repo"], "flakes_install", "github:user/repo"),
    (["nx", "-f", "-r", "-H", "github:user/repo"], "flakes_remove", "github:user/repo"),
    (["nx", "-f", "-H", "-r", "github:user/repo"], "flakes_remove", "github:user/repo"),
    (["nx", "-H", "-f", "-r", "github:user/repo"], "flakes_remove", "github:user/repo"),
    (["nx", "install", "firefox", "-H"], "install", "firefox"),
    (["nx", "install", "-H", "firefox"], "install", "firefox"),
], ids=[
    "-i -H firefox → install with requested=HOME",
    "-r -H firefox → remove with requested=HOME",
    "-f -H <url> → flakes install with requested=HOME",
    "-f -r -H <url> → flakes remove with requested=HOME",
    "-f -H -r <url> → same (-H between flags)",
    "-H -f -r <url> → same (-H first)",
    "long form: -H last still works (no regression)",
    "long form: -H before arg still works",
])
def test_home_flag_composition(argv, op, name, run_cli, cli_config):
    _, calls, _ = run_cli(argv)
    assert calls == [(op, (name, cli_config), {"requested": Target.HOME})]


# ── [5] Invalid combinations → exit 2, no handler runs ──────────────────────

@pytest.mark.parametrize("argv", [
    ["nx", "-i", "-r", "x"],
    ["nx", "-i", "-u"],
    ["nx", "-r", "-u"],
    ["nx", "-i", "install", "x"],
], ids=[
    "-i -r x → exit 2, nothing dispatched",
    "-i -u → exit 2, nothing dispatched",
    "-r -u → exit 2, nothing dispatched",
    "-i install x (short + subcommand) → exit 2",
])
def test_invalid_combinations_rejected(argv, run_cli):
    code, calls, _ = run_cli(argv)
    assert code == 2
    assert calls == []


# ── [6] upgrade -H rejected BEFORE any external command ─────────────────────

@pytest.mark.parametrize("argv,label", [
    (["nx", "upgrade", "-H"], "upgrade -H"),
    (["nx", "upgrade", "--home"], "upgrade --home"),
    (["nx", "upgrade", "-home"], "upgrade -home"),
    (["nx", "-u", "-H"], "-u -H (short form)"),
    (["nx", "flakes", "upgrade", "-H"], "flakes upgrade -H"),
    (["nx", "flakes", "update", "-H"], "flakes update -H"),
    (["nx", "-f", "-u", "-H"], "-f -u -H (short form)"),
], ids=[
    "upgrade -H → exit 1, no handler, no subprocess",
    "upgrade --home → exit 1, no handler, no subprocess",
    "upgrade -home → exit 1, no handler, no subprocess",
    "-u -H (short form) → exit 1, no handler, no subprocess",
    "flakes upgrade -H → exit 1, no handler, no subprocess",
    "flakes update -H → exit 1, no handler, no subprocess",
    "-f -u -H (short form) → exit 1, no handler, no subprocess",
])
def test_home_upgrade_rejected_before_execution(argv, label, run_cli):
    # The subprocess assertion uses the mock owned by ``run_cli``; the
    # original harness checked an outer mock that the inner patch shadowed,
    # making the assertion vacuous. This version actually verifies it.
    code, calls, mock_sub = run_cli(argv)
    assert code == 1, label
    assert calls == [], label
    assert not mock_sub.called, label


# ── [7] Plain upgrade unaffected ─────────────────────────────────────────────

def test_plain_upgrade_unaffected(run_cli, cli_config):
    _, calls, _ = run_cli(["nx", "upgrade"])
    assert calls == [("upgrade", (cli_config,), {})]
    _, calls, _ = run_cli(["nx", "flakes", "upgrade"])
    assert calls == [("flakes_upgrade", (cli_config,), {})]


# ── [8] Normalization pure-function checks ───────────────────────────────────

@pytest.mark.parametrize("argv,expected", [
    (["nx", "install", "firefox"], ["nx", "install", "firefox"]),
    (["nx", "-H", "install", "firefox"], ["nx", "-H", "install", "firefox"]),
    (["nx", "-f"], ["nx", "flakes"]),
    (["nx", "-f", "--home", "-r", "x"], ["nx", "flakes", "remove", "-H", "x"]),
    (["nx", "-f", "-r", "-home", "x"], ["nx", "flakes", "remove", "-H", "x"]),
], ids=[
    "no short flags → argv untouched",
    "long form with -H first untouched (argparse handles)",
    "-f alone with no arg → flakes",
    "--home alias works in short composition",
    "-home alias works in short composition",
])
def test_normalize_short_args(argv, expected):
    from main import _normalize_short_args
    assert _normalize_short_args(argv) == expected
