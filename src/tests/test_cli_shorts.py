"""Phase 5 CLI composition & validation tests.

All tests mock handlers and subprocess — no real nixos-rebuild, no real
nix flake update, no file changes. Verifies:
  - short forms -i/-r/-u/-f and compositions
  - -f defaults to install
  - long-form compatibility (incl. 'flakes install')
  - -H placement flexibility
  - invalid combinations rejected (exit 2)
  - upgrade -H / flakes upgrade -H / flakes update -H rejected BEFORE
    any external command runs (exit 1)
"""
import sys
import os
import io
from unittest.mock import patch, MagicMock
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

import main as m
from core.target import Target

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f" — {detail}" if not cond else ""))


CONFIG = {"setup": {
    "configuration_path": "/tmp/…/configuration.nix",
    "flake_enabled": True,
    "flake_path": "/tmp/…/flake.nix",
    "home_manager_enabled": True,
    "home_manager_path": "/tmp/…/home.nix",
}}


def run_cli(argv, expect_exit=None):
    """Run main() with all handlers + subprocess mocked.

    Returns (exit_code_or_None, handler_calls) where handler_calls is a list
    of (handler_name, args, kwargs). SystemExit is captured.
    """
    calls = []
    def rec(name):
        def f(*a, **k):
            calls.append((name, a, k))
        return f

    exit_code = None
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
        exit_code = e.code
    return exit_code, calls


print("=" * 70)
print("PHASE 5 — CLI COMPOSITION & VALIDATION")
print("=" * 70)

# ── Short commands ─────────────────────────────────────────────────────────
print("\n[1] Short commands reach the canonical handlers")

code, calls = run_cli(["nx", "-i", "firefox"])
check("-i firefox → handle_install(firefox)",
      calls == [("install", ("firefox", CONFIG), {"requested": None})])

code, calls = run_cli(["nx", "-r", "firefox"])
check("-r firefox → handle_remove(firefox)",
      calls == [("remove", ("firefox", CONFIG), {"requested": None})])

code, calls = run_cli(["nx", "-u"])
check("-u → handle_upgrade()", calls == [("upgrade", (CONFIG,), {})])

# ── Compositions ───────────────────────────────────────────────────────────
print("\n[2] -f compositions")

code, calls = run_cli(["nx", "-f", "github:user/repo"])
check("-f <url> → handle_flakes_install(url) (default install)",
      calls == [("flakes_install", ("github:user/repo", CONFIG), {"requested": None})])

code, calls = run_cli(["nx", "-f", "-i", "github:user/repo"])
check("-f -i <url> → handle_flakes_install(url) (explicit install)",
      calls == [("flakes_install", ("github:user/repo", CONFIG), {"requested": None})])

code, calls = run_cli(["nx", "-f", "-r", "github:user/repo"])
check("-f -r <name> → handle_flakes_remove(name)",
      calls == [("flakes_remove", ("github:user/repo", CONFIG), {"requested": None})])

code, calls = run_cli(["nx", "-f", "-u"])
check("-f -u → handle_flakes_upgrade()", calls == [("flakes_upgrade", (CONFIG,), {})])

# ── Long-form compatibility ────────────────────────────────────────────────
print("\n[3] Long forms unchanged")

code, calls = run_cli(["nx", "install", "firefox"])
check("install firefox → handle_install", calls[0][0] == "install")

code, calls = run_cli(["nx", "remove", "firefox"])
check("remove firefox → handle_remove", calls[0][0] == "remove")

code, calls = run_cli(["nx", "upgrade"])
check("upgrade → handle_upgrade", calls[0][0] == "upgrade")

code, calls = run_cli(["nx", "flakes", "github:user/repo"])
check("flakes <url> → handle_flakes_install", calls[0][0] == "flakes_install")

code, calls = run_cli(["nx", "flakes", "install", "github:user/repo"])
check("flakes install <url> → handle_flakes_install (explicit form preserved)",
      calls == [("flakes_install", ("github:user/repo", CONFIG), {"requested": None})])

code, calls = run_cli(["nx", "flakes", "remove", "x"])
check("flakes remove x → handle_flakes_remove", calls[0][0] == "flakes_remove")

code, calls = run_cli(["nx", "flakes", "upgrade"])
check("flakes upgrade → handle_flakes_upgrade", calls[0][0] == "flakes_upgrade")

code, calls = run_cli(["nx", "flakes", "update"])
check("flakes update → handle_flakes_upgrade (alias)", calls[0][0] == "flakes_upgrade")

# ── Home target composition ────────────────────────────────────────────────
print("\n[4] -H composition")

code, calls = run_cli(["nx", "-i", "-H", "firefox"])
check("-i -H firefox → install with requested=HOME",
      calls == [("install", ("firefox", CONFIG), {"requested": Target.HOME})])

code, calls = run_cli(["nx", "-r", "-H", "firefox"])
check("-r -H firefox → remove with requested=HOME",
      calls == [("remove", ("firefox", CONFIG), {"requested": Target.HOME})])

code, calls = run_cli(["nx", "-f", "-H", "github:user/repo"])
check("-f -H <url> → flakes install with requested=HOME",
      calls == [("flakes_install", ("github:user/repo", CONFIG), {"requested": Target.HOME})])

code, calls = run_cli(["nx", "-f", "-r", "-H", "github:user/repo"])
check("-f -r -H <url> → flakes remove with requested=HOME",
      calls == [("flakes_remove", ("github:user/repo", CONFIG), {"requested": Target.HOME})])

code, calls = run_cli(["nx", "-f", "-H", "-r", "github:user/repo"])
check("-f -H -r <url> → same (-H between flags)",
      calls == [("flakes_remove", ("github:user/repo", CONFIG), {"requested": Target.HOME})])

code, calls = run_cli(["nx", "-H", "-f", "-r", "github:user/repo"])
check("-H -f -r <url> → same (-H first)",
      calls == [("flakes_remove", ("github:user/repo", CONFIG), {"requested": Target.HOME})])

code, calls = run_cli(["nx", "install", "firefox", "-H"])
check("long form: -H last still works (no regression)",
      calls == [("install", ("firefox", CONFIG), {"requested": Target.HOME})])

code, calls = run_cli(["nx", "install", "-H", "firefox"])
check("long form: -H before arg still works",
      calls == [("install", ("firefox", CONFIG), {"requested": Target.HOME})])

# ── Invalid combinations ───────────────────────────────────────────────────
print("\n[5] Invalid combinations → exit 2, no handler runs")

for argv in (["nx", "-i", "-r", "x"], ["nx", "-i", "-u"], ["nx", "-r", "-u"]):
    code, calls = run_cli(argv)
    check(f"{' '.join(argv[1:])} → exit 2, nothing dispatched",
          code == 2 and calls == [], f"exit={code} calls={calls}")

code, calls = run_cli(["nx", "-i", "install", "x"])
check("-i install x (short + subcommand) → exit 2",
      code == 2 and calls == [])

# ── Unsupported Home upgrade ───────────────────────────────────────────────
print("\n[6] upgrade -H rejected BEFORE any external command")

for argv, label in (
    (["nx", "upgrade", "-H"], "upgrade -H"),
    (["nx", "upgrade", "--home"], "upgrade --home"),
    (["nx", "upgrade", "-home"], "upgrade -home"),
    (["nx", "-u", "-H"], "-u -H (short form)"),
    (["nx", "flakes", "upgrade", "-H"], "flakes upgrade -H"),
    (["nx", "flakes", "update", "-H"], "flakes update -H"),
    (["nx", "-f", "-u", "-H"], "-f -u -H (short form)"),
):
    with patch("main.subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0)
        code, calls = run_cli(argv)
        check(f"{label} → exit 1, no handler, no subprocess",
              code == 1 and calls == [] and not mock_sub.called,
              f"exit={code} calls={calls} sub={mock_sub.called}")

# ── Normal upgrade still works ─────────────────────────────────────────────
print("\n[7] Plain upgrade unaffected")

code, calls = run_cli(["nx", "upgrade"])
check("upgrade (no flag) → handle_upgrade normally", calls == [("upgrade", (CONFIG,), {})])

code, calls = run_cli(["nx", "flakes", "upgrade"])
check("flakes upgrade (no flag) → handle_flakes_upgrade normally",
      calls == [("flakes_upgrade", (CONFIG,), {})])

# ── Normalization unit checks ──────────────────────────────────────────────
print("\n[8] Normalization pure-function checks")

from main import _normalize_short_args as norm

check("no short flags → argv untouched",
      norm(["nx", "install", "firefox"]) == ["nx", "install", "firefox"])
check("long form with -H first untouched (argparse handles)",
      norm(["nx", "-H", "install", "firefox"]) == ["nx", "-H", "install", "firefox"])
check("-f alone with no arg → flakes",
      norm(["nx", "-f"]) == ["nx", "flakes"])
check("--home alias works in short composition",
      norm(["nx", "-f", "--home", "-r", "x"]) == ["nx", "flakes", "remove", "-H", "x"])
check("-home alias works in short composition",
      norm(["nx", "-f", "-r", "-home", "x"]) == ["nx", "flakes", "remove", "-H", "x"])


print("\n" + "=" * 70)
print(f"RESULTS: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    for f in FAIL:
        print(f"  ✗ {f}")
print("=" * 70)
sys.exit(1 if FAIL else 0)
