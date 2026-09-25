"""Beta audit 3/3 — flake discovery, install/remove integration, E2E sandbox.

READ-ONLY audit: asserts CORRECT behavior; failures document bugs.
All nix subprocesses mocked; files live in tempdirs.
"""
import sys
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from src.flakes.discovery import discover, classify
from src.flakes.resolver import parse_flake_url
from src.flakes.models import FlakeOutput
from src.core.writer import add_flake, remove_flake, remove_flake_reference, add_flake_overlay
from src.core.target import Target
from src.flakes.executor import execute
from src.flakes.models import FlakeSource, InstallationPlan

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f" — {detail}" if not cond else ""))


def fake_discover(json_payload, system="x86_64-linux"):
    """Run discover() with mocked nix commands."""
    with patch("src.flakes.discovery.subprocess.run") as mock_run:
        def side_effect(cmd, **kw):
            m = MagicMock()
            if "show" in cmd:
                m.returncode = 0
                m.stdout = json.dumps(json_payload)
            else:  # eval currentSystem
                m.returncode = 0
                m.stdout = system
            return m
        mock_run.side_effect = side_effect
        return discover(FlakeSource(url="github:x/y"))


print("=" * 70)
print("BETA AUDIT 3/3 — DISCOVERY / FLAKE OPS / E2E")
print("=" * 70)

# ── [A] Discovery adversarial ──────────────────────────────────────────────
print("\n[A] discovery adversarial")

out = fake_discover({"packages": {"x86_64-linux": {"default": {}, "vim": {}, "htop": {}}}})
check("A1 default ordered first",
      out and out[0].name == "default" and len(out) == 3)

out = fake_discover({"packages": {"aarch64-darwin": {"vim": {}}}})   # wrong system
check("A2 wrong-system outputs excluded", out == [])

out = fake_discover({"packages": {"x86_64-linux": "not-a-dict"}})
check("A3 non-dict system content skipped", out == [])

out = fake_discover({"packages": "not-a-dict"})
check("A4 non-dict type content skipped", out == [])

out = fake_discover({"hydraJobs": {"x86_64-linux": {"x": {}}}})
check("A5 unknown output type (hydraJobs) ignored", out == [])

out = fake_discover({})
check("A6 empty outputs → empty list", out == [])

out = fake_discover({"packages": {"x86_64-linux": {}}, "overlays": {"default": {}}})
check("A7 empty system dict + overlay present → overlay only",
      len(out) == 1 and out[0].type == "overlays")

# A8: malformed JSON from nix
with patch("src.flakes.discovery.subprocess.run") as mr:
    m = MagicMock(); m.returncode = 0; m.stdout = "{invalid json"
    mr.return_value = m
    try:
        out = discover(FlakeSource(url="github:x/y"))
        check("A8 malformed JSON → handled (empty or exception)", out == [])
    except json.JSONDecodeError:
        check("A8 malformed JSON → handled (empty or exception)", False,
              "json.JSONDecodeError propagates uncaught to caller")

# A9: nix failure (non-zero)
with patch("src.flakes.discovery.subprocess.run") as mr:
    m = MagicMock(); m.returncode = 1; m.stdout = ""
    mr.return_value = m
    out = discover(FlakeSource(url="github:x/y"))
    check("A9 nix failure → empty list", out == [])

# ── [B] classify coverage ──────────────────────────────────────────────────
print("\n[B] classify")

for t, expected in [("packages", "installable"), ("legacyPackages", "installable"),
                    ("nixosModules", "configurable"), ("homeManagerModules", "configurable"),
                    ("apps", "executable"), ("overlays", "overlay"),
                    ("devShells", "unsupported"), ("checks", "unsupported"),
                    ("bogusType", "unsupported")]:
    got = classify(FlakeOutput(name="x", type=t))
    check(f"B {t} → {expected}", got == expected, f"got {got}")

# ── [C] resolver ───────────────────────────────────────────────────────────
print("\n[C] resolver")

s = parse_flake_url("github:user/repo#packages.x86_64-linux.vim")
check("C1 URL with # target split", s.url == "github:user/repo" and s.target == "packages.x86_64-linux.vim")

s = parse_flake_url("github:user/repo")
check("C2 plain URL", s.url == "github:user/repo" and s.target is None)

# ── [D] add_flake / remove round trips (writer level) ─────────────────────
print("\n[D] flake writer round trips")

FLAKE = '{\n  inputs = {\n    nixpkgs.url = "github:NixOS/nixpkgs";\n  };\n  outputs = { nixpkgs, ... }: {\n  };\n}\n'
HOME = '{ pkgs, ... }:\n{\n  home.packages = with pkgs; [\n    git\n  ];\n}\n'
SYS = '{ pkgs, ... }:\n{\n  environment.systemPackages = with pkgs; [\n    git\n  ];\n}\n'

fc, hc, st = add_flake(FLAKE, "test-flake", "github:x/y", "default", "package",
                       home_content=HOME, block="home.packages")
check("D1 add_flake HOME: input in flake, ref in home, status success",
      'url = "github:x/y"' in fc and "inputs.test-flake.packages" in hc and st == "success")

# D2: repeated install — input must not duplicate
fc2, hc2, st2 = add_flake(fc, "test-flake", "github:x/y", "default", "package",
                          home_content=hc, block="home.packages")
input_count = fc2.count('url = "github:x/y"')
check("D2 repeated install: input not duplicated, status success",
      input_count == 1 and st2 == "success", f"input occurrences: {input_count}")

# D3: remove_flake on real structure
fc3, found = remove_flake(fc2, "test-flake")
check("D3 remove_flake removes input", found and "test-flake" not in fc3)

# D4: remove_flake_reference with unusual-but-valid formatting
weird = '  inputs.x.packages.${ pkgs.system }.default\n'
out, found = remove_flake_reference(weird, "x")
check("D4 reference with spaces inside ${ } matched",
      found, f"found={found!r} out={out!r}")

# D5: overlay ref removal with attr != default
ov = '    inputs.x.overlays.my-overlay\n'
out, found = remove_flake_reference(ov, "x")
check("D5 non-default overlay attr removed", found)

# ── [E] executor integration (sandboxed) ───────────────────────────────────
print("\n[E] executor integration")

def make_plan(action="install", pkg_type="packages", name="default"):
    return InstallationPlan(
        source=FlakeSource(url="github:x/y", revision="abc"),
        output=FlakeOutput(name=name, type=pkg_type, attribute=f"{pkg_type}.x86_64-linux.{name}"),
        action=action, system="x86_64-linux", flake_name="repo")

def make_config(td, flake_enabled=True, hm=True):
    return {"setup": {
        "configuration_path": str(Path(td) / "configuration.nix"),
        "flake_enabled": flake_enabled,
        "flake_path": str(Path(td) / "flake.nix"),
        "home_manager_enabled": hm,
        "home_manager_path": str(Path(td) / "home.nix"),
        "unstable_variable": "unstable",
    }}

def setup_env(td, sys_text=None, home_text=None, flake_text=FLAKE):
    if flake_text is not None:
        Path(td, "flake.nix").write_text(flake_text)
    if sys_text is not None:
        Path(td, "configuration.nix").write_text(sys_text)
    if home_text is not None:
        Path(td, "home.nix").write_text(home_text)

def run_exec(td, plan, config, target=None):
    with patch("src.flakes.executor.subprocess.run") as mr, \
         patch("src.flakes.executor.backup_files"), \
         patch("src.flakes.executor.restore_files"):
        mr.return_value = MagicMock(returncode=0)
        ok = execute(plan, config, target=target)
        rebuild_cmd = mr.call_args[0][0] if mr.called else None
    return ok, rebuild_cmd

# E1: flake install SYSTEM — rebuild must use --flake (not plain switch)
with tempfile.TemporaryDirectory() as td:
    setup_env(td, sys_text=SYS, home_text=HOME)
    ok, cmd = run_exec(td, make_plan(), make_config(td))
    check("E1 rebuild uses nixos-rebuild switch --flake",
          ok and cmd and cmd[0] == "nixos-rebuild" and "--flake" in cmd,
          f"ok={ok} cmd={cmd}")

# E2: flake_enabled=false — executor still rebuilds with --flake?
with tempfile.TemporaryDirectory() as td:
    setup_env(td, sys_text=SYS, home_text=HOME)
    ok, cmd = run_exec(td, make_plan(), make_config(td, flake_enabled=False))
    check("E2 non-flake path rebuild command (record actual)",
          cmd is not None, f"ok={ok} cmd={cmd}")

# E3: flake missing entirely (flake_enabled=true, no flake.nix)
with tempfile.TemporaryDirectory() as td:
    setup_env(td, sys_text=SYS, home_text=HOME, flake_text=None)
    if Path(td, "flake.nix").exists():
        Path(td, "flake.nix").unlink()
    ok, cmd = run_exec(td, make_plan(), make_config(td))
    check("E3 missing flake.nix → False, no rebuild", ok is False and cmd is None,
          f"ok={ok} cmd={cmd}")

# E4: install with target=HOME but home.nix missing
with tempfile.TemporaryDirectory() as td:
    setup_env(td, sys_text=SYS, home_text=None)
    ok, cmd = run_exec(td, make_plan(), make_config(td), target=Target.HOME)
    check("E4 HOME target without home.nix → False, no rebuild",
          ok is False and cmd is None, f"ok={ok} cmd={cmd}")

# E5: unmanaged-reference refusal is handler-level; executor overlay+HOME (record)
with tempfile.TemporaryDirectory() as td:
    setup_env(td, sys_text=SYS, home_text=HOME)
    ok, cmd = run_exec(td, make_plan(action="overlay", pkg_type="overlays"),
                       make_config(td), target=Target.HOME)
    home_after = Path(td, "home.nix").read_text()
    check("E5 overlay + HOME target: overlay written to home.nix (semantics undefined — record)",
          "nixpkgs.overlays" in home_after,
          f"overlay landed in home.nix: {'nixpkgs.overlays' in home_after}")

# ── [F] E2E sandbox: full install→remove cycle via handlers ───────────────
print("\n[F] E2E sandbox — handler level")

import io
from contextlib import redirect_stdout

def run_handler_install(url, config, requested=None):
    outs = [FlakeOutput(name="default", type="packages", attribute="packages.x86_64-linux.default")]
    with patch("main.parse_flake_url", return_value=FlakeSource(url=url)), \
         patch("main.get_metadata", return_value=FlakeSource(url=url)), \
         patch("main.discover", return_value=outs), \
         patch("main.get_current_system", return_value="x86_64-linux"), \
         patch("main.show_results_flake", return_value=[outs[0]]), \
         patch("main.show_summary", return_value=True), \
         patch("main.show_rebuild_start"), patch("main.show_rebuild_done"), \
         patch("main.subprocess.run") as mr, \
         patch("main.backup_files"), patch("main.restore_files"), \
         patch("src.flakes.executor.backup_files"), \
         patch("src.flakes.executor.restore_files"), \
         redirect_stdout(io.StringIO()):
        mr.return_value = MagicMock(returncode=0)
        main_mod.handle_flakes_install(url, config, requested=requested)

import main as main_mod

with tempfile.TemporaryDirectory() as td:
    setup_env(td, sys_text=SYS, home_text=HOME)
    cfg = make_config(td)
    run_handler_install("github:test/repo", cfg)  # SYSTEM default
    sys_txt = Path(td, "configuration.nix").read_text()
    home_txt = Path(td, "home.nix").read_text()
    check("F1 E2E install SYSTEM: ref in configuration.nix",
          "inputs.repo.packages" in sys_txt)
    check("F2 E2E install SYSTEM: home.nix untouched",
          home_txt == HOME)

with tempfile.TemporaryDirectory() as td:
    setup_env(td, sys_text=SYS, home_text=HOME)
    cfg = make_config(td)
    run_handler_install("github:test/repo", cfg, requested=Target.HOME)
    home_txt = Path(td, "home.nix").read_text()
    sys_txt = Path(td, "configuration.nix").read_text()
    check("F3 E2E install HOME: ref in home.nix",
          "inputs.repo.packages" in home_txt)
    check("F4 E2E install HOME: configuration.nix untouched",
          sys_txt == SYS)

# F5: unmanaged reference refusal (handler level)
with tempfile.TemporaryDirectory() as td:
    setup_env(td, sys_text=SYS, home_text=HOME)
    # put an unmanaged ref in configuration.nix
    Path(td, "configuration.nix").write_text(SYS.replace(
        "git", "git\n    inputs.evil-flake.someCustom.thing"))
    cfg = make_config(td)
    with patch("main.subprocess.run") as mr, \
         patch("main.backup_files"), patch("main.restore_files"), \
         redirect_stdout(io.StringIO()) as buf:
        mr.return_value = MagicMock(returncode=0)
        main_mod.handle_flakes_remove("evil-flake", cfg)
    check("F5 unmanaged reference → refused, no rebuild",
          not mr.called and "unmanaged" in buf.getvalue(),
          f"subprocess_called={mr.called}")

# F6: repeated remove of same flake
with tempfile.TemporaryDirectory() as td:
    setup_env(td, sys_text=SYS, home_text=HOME)
    cfg = make_config(td)
    run_handler_install("github:test/repo", cfg)
    with patch("main.subprocess.run") as mr, patch("main.backup_files"), \
         patch("main.restore_files"), redirect_stdout(io.StringIO()):
        mr.return_value = MagicMock(returncode=0)
        main_mod.handle_flakes_remove("repo", cfg)
        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            main_mod.handle_flakes_remove("repo", cfg)
    check("F6 second remove → 'not found or was not added by nx'",
          "not found" in buf2.getvalue(), f"msg={buf2.getvalue()!r:.80}")

print("\n" + "=" * 70)
print(f"RESULTS: {len(PASS)} passed, {len(FAIL)} failed (failures = findings)")
if FAIL:
    for f in FAIL:
        print(f"  ✗ FINDING: {f}")
print("=" * 70)
sys.exit(0)
