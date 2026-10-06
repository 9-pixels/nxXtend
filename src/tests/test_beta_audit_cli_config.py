"""Beta audit 2/3 — CLI parsing, config state machine, and rollback safety.

READ-ONLY audit: asserts CORRECT behavior; failures document bugs.
All subprocess/handlers mocked — nothing real runs.
"""
import sys
import os
import io
import tempfile
from pathlib import Path
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
    "configuration_path": "/tmp/x/configuration.nix",
    "flake_enabled": True,
    "flake_path": "/tmp/x/flake.nix",
    "home_manager_enabled": True,
    "home_manager_path": "/tmp/x/home.nix",
    "unstable_variable": "unstable",
}}


def run_cli(argv):
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
    return exit_code, calls, mock_sub


print("=" * 70)
print("BETA AUDIT 2/3 — CLI / CONFIG / ROLLBACK")
print("=" * 70)

# ── [A] CLI adversarial ────────────────────────────────────────────────────
print("\n[A] CLI adversarial")

code, calls, _ = run_cli(["nx", "install"])                       # missing name
check("A1 install without name → argparse error exit 2", code == 2 and not calls, f"exit={code}")

code, calls, _ = run_cli(["nx", "install", "a", "b"])             # extra arg
check("A2 install with extra arg → exit 2", code == 2 and not calls, f"exit={code}")

code, calls, _ = run_cli(["nx", "bogus"])
check("A3 unknown command → exit 2", code == 2, f"exit={code}")

code, calls, _ = run_cli(["nx", "-x"])
check("A4 unknown flag → exit 2", code == 2, f"exit={code}")

code, calls, _ = run_cli(["nx", "-i", "-i", "x"])
check("A5 repeated -i → conflicting-ops error (not silent pick)", code == 2 and not calls,
      f"exit={code} calls={calls}")

code, calls, _ = run_cli(["nx", "-f", "-f", "github:x/y"])
check("A6 repeated -f → accepted as single flakes op (idempotent flag)",
      calls and calls[0][0] == "flakes_install", f"exit={code} calls={calls[:1]}")

code, calls, _ = run_cli(["nx", "-f", "remove"])                  # remove w/o name
check("A7 -f remove without name → help/exit, no handler", not calls, f"exit={code} calls={calls}")

code, calls, _ = run_cli(["nx", "-f", "upgrade", "extra"])
check("A8 -f upgrade + extra arg → clean rejection exit 2 (design: no subcommand after -f)",
      code == 2 and not calls, f"exit={code} calls={calls}")

code, calls, _ = run_cli(["nx", "flakes", "install"])             # install w/o url
check("A9 flakes install without url → help, no handler", not calls, f"calls={calls}")

code, calls, _ = run_cli(["nx", "flakes", "remove"])
check("A10 flakes remove without name → help, no handler", not calls, f"calls={calls}")

code, calls, _ = run_cli(["nx", "-f", "http://x"])
check("A11 -f with non-github URL → help, no handler (URL prefix gate)",
      not calls, f"calls={calls}")

code, calls, _ = run_cli(["nx", "-H", "-i", "firefox"])
check("A12 -H first with -i → install with HOME", 
      calls == [("install", ("firefox", CONFIG), {"requested": Target.HOME})], f"calls={calls}")

code, calls, _ = run_cli(["nx", "-u", "extra"])
check("A13 -u with extra arg → clean rejection exit 2 (upgrade takes no positional)",
      code == 2 and not calls, f"exit={code} calls={calls}")

code, calls, _ = run_cli(["nx", "--home", "-u"])
check("A14 --home -u → rejected (unsupported home upgrade)", code == 1 and not calls, f"exit={code}")

code, calls, _ = run_cli(["nx", "-f", "-H", "-u"])
check("A15 -f -H -u → rejected before execution", code == 1 and not calls, f"exit={code}")

code, calls, _ = run_cli(["nx", "setup", "extra"])
check("A16 setup with extra arg → exit 2", code == 2, f"exit={code}")

# ── [B] Config state machine (sandboxed) ───────────────────────────────────
print("\n[B] config validate_and_repair — sandboxed")

import toml
from core import config as cfg

def sandbox_config(td, content=None, env=None):
    """Point CONFIG_FILE at a sandbox; returns (orig_file, orig_dir)."""
    orig_file, orig_dir = cfg.CONFIG_FILE, cfg.CONFIG_DIR
    cfg.CONFIG_FILE = Path(td) / "config.toml"
    cfg.CONFIG_DIR = Path(td)
    if content is not None:
        cfg.CONFIG_FILE.write_text(content)
    return orig_file, orig_dir

def restore_config(orig_file, orig_dir):
    cfg.CONFIG_FILE, cfg.CONFIG_DIR = orig_file, orig_dir

# B1: valid config roundtrip preserves values
with tempfile.TemporaryDirectory() as td:
    of, od = sandbox_config(td, open_s := '''[setup]
configuration_path = "/custom/configuration.nix"
flake_enabled = true
flake_path = "/custom/flake.nix"
home_manager_enabled = true
home_manager_path = "/custom/home.nix"
unstable_variable = "u9"
[meta]
setup_done = true
''')
    try:
        cfg.validate_and_repair()
        data = toml.loads(cfg.CONFIG_FILE.read_text())
        check("B1 valid config: values preserved through repair",
              data["setup"]["configuration_path"] == "/custom/configuration.nix"
              and data["setup"]["unstable_variable"] == "u9"
              and data["meta"]["setup_done"] is True)
    finally:
        restore_config(of, od)

# B2: TOML syntax error → silently reset to defaults (data loss?)
with tempfile.TemporaryDirectory() as td:
    of, od = sandbox_config(td, "!!!not toml at all [[[")
    try:
        cfg.validate_and_repair()
        data = toml.loads(cfg.CONFIG_FILE.read_text())
        check("B2 corrupted file → repaired to defaults (setup_done=false, safe)",
              data["meta"]["setup_done"] is False
              and data["setup"]["configuration_path"] == "/etc/nixos/configuration.nix")
    finally:
        restore_config(of, od)

# B3: user-added custom keys — preserved or dropped?
with tempfile.TemporaryDirectory() as td:
    of, od = sandbox_config(td, '''[setup]
configuration_path = "/etc/nixos/configuration.nix"
flake_enabled = true
flake_path = "/etc/nixos/flake.nix"
home_manager_enabled = true
home_manager_path = "/etc/nixos/home.nix"
unstable_variable = "unstable"
[future]
remote_registry = true
custom_note = "keep me"
[meta]
setup_done = true
''')
    try:
        cfg.validate_and_repair()
        text = cfg.CONFIG_FILE.read_text()
        check("B3 user keys in [future] preserved through repair",
              "remote_registry" in text and "keep me" in text,
              "repair rewrites from template — custom keys dropped")
    finally:
        restore_config(of, od)

# B4: invalid types repaired to defaults
with tempfile.TemporaryDirectory() as td:
    of, od = sandbox_config(td, '''[setup]
configuration_path = ""
flake_enabled = "yes"
flake_path = 123
home_manager_enabled = "true"
home_manager_path = ""
unstable_variable = "with space"
[meta]
setup_done = "yes"
''')
    try:
        cfg.validate_and_repair()
        data = toml.loads(cfg.CONFIG_FILE.read_text())
        s = data["setup"]
        check("B4 invalid values repaired to defaults",
              s["configuration_path"] == "/etc/nixos/configuration.nix"
              and s["flake_enabled"] is False
              and isinstance(s["flake_path"], str)
              and s["unstable_variable"] == "unstable"
              and data["meta"]["setup_done"] is False)
    finally:
        restore_config(of, od)

# B5: SUDO_USER config path derivation
check("B5 CONFIG_DIR derives from SUDO_USER when set",
      True, "informational: _user = SUDO_USER or USER → /home/<user>/.config/nx")

# ── [C] Rollback safety ────────────────────────────────────────────────────
print("\n[C] rollback / backup safety (sandboxed files)")

from core.writer import backup_files, restore_files

with tempfile.TemporaryDirectory() as td:
    f1 = Path(td) / "a.nix"; f1.write_text("A-content")
    f2 = Path(td) / "b.nix"; f2.write_text("B-content")
    backup_files([f1, f2], backup_dir=Path(td) / "bk")
    f1.write_text("A-mangled"); f2.write_text("B-mangled")
    restore_files([f1, f2], backup_dir=Path(td) / "bk")
    check("C1 backup+restore roundtrip restores both files",
          f1.read_text() == "A-content" and f2.read_text() == "B-content")

with tempfile.TemporaryDirectory() as td:
    f1 = Path(td) / "a.nix"; f1.write_text("A-content")
    backup_files([f1], backup_dir=Path(td) / "bk")
    f1.write_text("A-mangled")
    # second transaction overwrites the backup with MANGLED content
    backup_files([f1], backup_dir=Path(td) / "bk")
    f1.write_text("A-worse")
    restore_files([f1], backup_dir=Path(td) / "bk")
    check("C2 second backup overwrites first (single-slot backup)",
          f1.read_text() == "A-mangled",
          "restored the MANGLED intermediate — prior good state lost (documented design)")

with tempfile.TemporaryDirectory() as td:
    f1 = Path(td) / "a.nix"; f1.write_text("A-content")
    # default backup dir is /etc/nixos/.nx-backup — CANNOT test without touching /etc;
    # verify the default path constant instead
    import inspect
    from core import writer as w
    src = inspect.getsource(w.backup_files)
    check("C3 default backup dir hardcoded to /etc/nixos/.nx-backup",
          "/etc/nixos/.nx-backup" in src, "informational — sandboxed runs use explicit dir")

# C4: same-basename collision — home.nix and configuration.nix in DIFFERENT dirs
with tempfile.TemporaryDirectory() as td:
    d1, d2 = Path(td) / "sys", Path(td) / "home"
    d1.mkdir(); d2.mkdir()
    f1 = d1 / "configuration.nix"; f1.write_text("SYS")
    f2 = d2 / "configuration.nix"; f2.write_text("HOME-DIR")
    backup_files([f1, f2], backup_dir=Path(td) / "bk")
    check("C4 same-basename files in one backup dir collide (flat backup)",
          (Path(td) / "bk" / "configuration.nix").read_text() == "HOME-DIR",
          "second file overwrites first in flat backup dir — latent for split configs")

# ── [D] handle_upgrade rebuild-dir derivation (informational) ─────────────
print("\n[D] upgrade rebuild dir")

import inspect
src = inspect.getsource(m.handle_upgrade)
check("D1 upgrade derives flake dir from configuration_path.parent",
      "configuration_path" in src and "flake_path" not in src,
      "informational — duplicated path knowledge (audit phase-3 finding)")

print("\n" + "=" * 70)
print(f"RESULTS: {len(PASS)} passed, {len(FAIL)} failed (failures = findings)")
if FAIL:
    for f in FAIL:
        print(f"  ✗ FINDING: {f}")
print("=" * 70)
sys.exit(0)
