"""Error reporting — every failure must reach the user, immediately and whole.

These tests pin the contract behind ``ui.display.show_error`` and
``ui.display.show_command_error`` and verify that each formerly-silent
failure path now reports itself:

* ``nix flake metadata`` failure / timeout   (flakes.resolver.get_metadata)
* ``nix flake show`` failure / timeout       (flakes.discovery.discover)
* output-type probe failure / timeout        (flakes.discovery._probe_output_type)
* ``nix eval builtins.currentSystem``        (flakes.discovery.get_current_system)
* ``nix flake update`` failure / timeout     (main.handle_flakes_upgrade)
* configuration write failure                (flakes.executor.execute)
* configuration modification failure         (core.writer.add_package)
* rollback failure after a failed rebuild    (main.handle_*)

The writer deliberately does not print: it returns the exception text on
``AddResult.error`` and the caller — which owns the display layer — shows it.
"""
import io
import subprocess
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.target import SYSTEM_BLOCK
from core.writer import AddResult, add_flake, add_package
from flakes.discovery import _probe_output_type, discover, get_current_system
from flakes.executor import execute
from flakes.models import FlakeOutput, FlakeSource, InstallationPlan
from flakes.resolver import get_metadata
from ui.display import show_command_error, show_error, timeout_detail

import main as main_mod


SYS = '{  environment.systemPackages = with pkgs; [\n    git\n  ];\n}'
FLAKE = '{\n  inputs = {\n    nixpkgs.url = "github:NixOS/nixpkgs";\n  };\n  outputs = { nixpkgs, ... }: {\n  };\n}\n'


def _completed(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def _timeout(**kwargs):
    return subprocess.TimeoutExpired(cmd=kwargs.pop("cmd", "nix"), timeout=120)


# ── display primitives ──────────────────────────────────────────────────────

def test_show_error_prints_title_and_full_detail(capsys):
    show_error("something broke", "line one\nline two\nline three")
    out = capsys.readouterr().out
    assert "something broke" in out
    assert "line one" in out
    assert "line two" in out
    assert "line three" in out


def test_show_error_keeps_long_output_intact(capsys):
    detail = "\n".join(f"stderr line {i}" for i in range(40))
    show_error("nix failed", detail)
    out = capsys.readouterr().out
    assert "stderr line 0" in out
    assert "stderr line 39" in out


def test_show_error_without_detail(capsys):
    show_error("something broke")
    out = capsys.readouterr().out
    assert "something broke" in out
    assert "None" not in out


def test_show_error_with_blank_detail(capsys):
    show_error("something broke", "   \n  \n")
    assert "something broke" in capsys.readouterr().out


def test_show_command_error_reports_command_and_stderr(capsys):
    show_command_error(["nix", "flake", "show", "github:x/y"],
                       _completed(1, "", "error: boom"))
    out = capsys.readouterr().out
    assert "exit 1" in out
    assert "nix flake show github:x/y" in out
    assert "error: boom" in out


def test_show_command_error_falls_back_to_stdout(capsys):
    show_command_error(["nix", "flake", "metadata"],
                       _completed(1, "stdout says no", ""))
    assert "stdout says no" in capsys.readouterr().out


def test_show_command_error_falls_back_to_extra(capsys):
    show_command_error(["nix", "flake", "show"], _completed(1),
                       extra="no output at all")
    assert "no output at all" in capsys.readouterr().out


def test_timeout_detail_includes_partial_stdout():
    exc = subprocess.TimeoutExpired(cmd="nix", timeout=120)
    exc.stdout = b"error: fetch failed\n"
    detail = timeout_detail(exc, 120)
    assert "timed out after 120s" in detail
    assert "error: fetch failed" in detail


def test_timeout_detail_handles_str_and_missing_output():
    exc = subprocess.TimeoutExpired(cmd="nix", timeout=5)
    exc.stderr = b"partial stderr"
    assert "partial stderr" in timeout_detail(exc, 5)

    empty = subprocess.TimeoutExpired(cmd="nix", timeout=5)
    assert timeout_detail(empty, 5) == "timed out after 5s"


# ── resolver ────────────────────────────────────────────────────────────────

def test_get_metadata_failure_is_reported():
    with patch("flakes.resolver.subprocess.run",
               return_value=_completed(1, "", "error: bad ref")), \
         patch("flakes.resolver.show_command_error") as mock_show:
        get_metadata(FlakeSource(url="github:x/y"))
    assert mock_show.call_count == 1
    args = mock_show.call_args[0]
    assert args[0] == ["nix", "flake", "metadata", "--json", "github:x/y"]
    assert args[1].stderr == "error: bad ref"


def test_get_metadata_empty_output_is_reported():
    with patch("flakes.resolver.subprocess.run", return_value=_completed(0)), \
         patch("flakes.resolver.show_command_error") as mock_show:
        get_metadata(FlakeSource(url="github:x/y"))
    assert mock_show.called


def test_get_metadata_timeout_is_reported_and_contract_preserved():
    """A timeout must not escape, and the source must still be returned."""
    with patch("flakes.resolver.subprocess.run", side_effect=_timeout(timeout=60)), \
         patch("flakes.resolver.show_error") as mock_show:
        out = get_metadata(FlakeSource(url="github:x/y"))
    assert out.url == "github:x/y"
    assert out.revision is None
    assert mock_show.called
    assert "timed out" in str(mock_show.call_args)


def test_get_metadata_timeout_keeps_partial_output():
    """A command that printed a diagnostic before hanging still shows it."""
    exc = subprocess.TimeoutExpired(cmd="nix", timeout=60)
    exc.stderr = b"error: resolving host"
    with patch("flakes.resolver.subprocess.run", side_effect=exc), \
         patch("flakes.resolver.show_error") as mock_show:
        get_metadata(FlakeSource(url="github:x/y"))
    assert "resolving host" in str(mock_show.call_args)


# ── discovery ───────────────────────────────────────────────────────────────

def test_discover_reports_the_show_failure_specifically():
    """The `flake show` failure must be reported on its own merits.

    The fallback runs its own probes afterwards, so a bare ``called``
    assertion would pass even if the show failure were never reported.
    """
    def side_effect(cmd, **kw):
        if "show" in cmd:
            return _completed(1, "", "error: broken darwin output")
        return _completed(1, "", "error: unable to download")

    with patch("flakes.discovery.subprocess.run", side_effect=side_effect), \
         patch("flakes.discovery.get_current_system", return_value="x86_64-linux"), \
         patch("flakes.discovery.show_command_error") as mock_show:
        discover(FlakeSource(url="github:x/y"))

    assert mock_show.call_count == 1, (
        "exactly the `flake show` failure should be reported through "
        f"show_command_error, got {mock_show.call_count} calls"
    )
    command, result = mock_show.call_args[0]
    assert "show" in command
    assert "broken darwin output" in result.stderr


def test_discover_empty_output_is_reported():
    with patch("flakes.discovery.subprocess.run", return_value=_completed(0)), \
         patch("flakes.discovery.show_error") as mock_show:
        out = discover(FlakeSource(url="github:x/y"))
    assert out == []
    assert mock_show.called


def test_discover_timeout_is_reported_and_not_retried():
    with patch("flakes.discovery.subprocess.run", side_effect=_timeout(timeout=120)), \
         patch("flakes.discovery._probe_output_type") as mock_probe, \
         patch("flakes.discovery.show_error") as mock_show:
        out = discover(FlakeSource(url="github:x/y"))
    assert out == []
    assert not mock_probe.called, "fallback must not run after a timeout"
    assert "timed out" in str(mock_show.call_args)


def test_discover_timeout_keeps_partial_output():
    exc = subprocess.TimeoutExpired(cmd="nix", timeout=120)
    exc.stdout = b"evaluating 'packages'"
    with patch("flakes.discovery.subprocess.run", side_effect=exc), \
         patch("flakes.discovery.show_error") as mock_show:
        discover(FlakeSource(url="github:x/y"))
    assert "evaluating 'packages'" in str(mock_show.call_args)


def test_probe_timeout_is_reported():
    with patch("flakes.discovery.subprocess.run", side_effect=_timeout(timeout=300)):
        probe = _probe_output_type("github:x/y", "packages.x86_64-linux")
    assert probe.names is None
    assert probe.timed_out is True
    assert "timed out" in probe.error


def test_get_current_system_failure_is_reported():
    with patch("flakes.discovery.subprocess.run",
               return_value=_completed(1, "", "error: eval blocked")), \
         patch("flakes.discovery.show_command_error") as mock_show:
        system = get_current_system()
    assert mock_show.called
    assert system.endswith("-linux") or system.endswith("-darwin")


def test_get_current_system_timeout_falls_back():
    with patch("flakes.discovery.subprocess.run", side_effect=_timeout(timeout=60)), \
         patch("flakes.discovery.show_error") as mock_show:
        system = get_current_system()
    assert mock_show.called
    assert system.endswith("-linux") or system.endswith("-darwin")


# ── flake update ────────────────────────────────────────────────────────────

def _upgrade_config(tmp_path):
    return {"setup": {"flake_enabled": True,
                      "flake_path": str(Path(tmp_path) / "flake.nix")}}


def test_flake_update_failure_is_not_reported_as_a_rebuild():
    buf = io.StringIO()
    with patch("main.subprocess.run",
               return_value=_completed(1, "", "error: lock file conflict")), \
         redirect_stdout(buf):
        main_mod.handle_flakes_upgrade(_upgrade_config(tempfile.gettempdir()))
    out = buf.getvalue()
    assert "flake update" in out, out
    assert "nixos-rebuild failed" not in out, (
        "a failed input update must not claim a rebuild was reverted"
    )


def test_flake_update_timeout_is_reported():
    with patch("main.subprocess.run", side_effect=_timeout(timeout=300)), \
         patch("main.show_error") as mock_show:
        main_mod.handle_flakes_upgrade(_upgrade_config(tempfile.gettempdir()))
    assert mock_show.called
    assert "timed out" in str(mock_show.call_args)


# ── executor ────────────────────────────────────────────────────────────────

def _plan():
    return InstallationPlan(
        source=FlakeSource(url="github:x/y", revision="abc"),
        output=FlakeOutput(name="default", type="packages",
                           attribute="packages.x86_64-linux.default"),
        action="install", system="x86_64-linux", flake_name="repo",
    )


def _config(td, flake_enabled=True):
    return {"setup": {
        "configuration_path": str(Path(td) / "configuration.nix"),
        "flake_enabled": flake_enabled,
        "flake_path": str(Path(td) / "flake.nix"),
        "home_manager_enabled": True,
        "home_manager_path": str(Path(td) / "home.nix"),
        "unstable_variable": "unstable",
    }}


def test_executor_write_failure_is_reported(tmp_path):
    Path(tmp_path, "flake.nix").write_text(FLAKE)
    Path(tmp_path, "configuration.nix").write_text(SYS)
    Path(tmp_path, "home.nix").write_text(SYS)
    with patch("flakes.executor.subprocess.run") as mr, \
         patch("flakes.executor.backup_files"), \
         patch("flakes.executor.restore_files"), \
         patch("pathlib.Path.write_text", side_effect=OSError("disk full")), \
         patch("flakes.executor.show_error") as mock_show:
        mr.return_value = MagicMock(returncode=0)
        ok = execute(_plan(), _config(tmp_path))
    assert ok is False
    assert "disk full" in str(mock_show.call_args)


def test_executor_reports_an_add_package_exception(tmp_path):
    Path(tmp_path, "flake.nix").write_text(FLAKE)
    Path(tmp_path, "configuration.nix").write_text(SYS)
    Path(tmp_path, "home.nix").write_text(SYS)
    result = AddResult(content=SYS, status="error", error="RuntimeError('boom')")
    with patch("flakes.executor.subprocess.run") as mr, \
         patch("flakes.executor.backup_files"), \
         patch("flakes.executor.restore_files"), \
         patch("flakes.executor.add_package", return_value=result), \
         patch("flakes.executor.show_error") as mock_show:
        mr.return_value = MagicMock(returncode=0)
        ok = execute(_plan(), _config(tmp_path, flake_enabled=False))
    assert ok is False
    assert "boom" in str(mock_show.call_args)


# ── writer ──────────────────────────────────────────────────────────────────

def test_add_package_exception_carries_its_text():
    """The writer reports through AddResult; it does not print."""
    with patch("core.writer.add_package_with_pkgs", side_effect=RuntimeError("boom")):
        res = add_package(SYS, "git", Path("/tmp"))
    assert res.status == "error"
    assert "boom" in res.error


def test_install_reports_an_add_package_exception(tmp_path):
    """The caller owns the display: it shows what the writer returned."""
    config_nix = tmp_path / "configuration.nix"
    config_nix.write_text(SYS)
    config = {"setup": {"configuration_path": str(config_nix),
                        "flake_enabled": False}}

    pkg = MagicMock()
    pkg.name = "vim"
    pkg.attribute = "vim"
    pkg.source = "stable"
    pkg.version = "9.0"

    def mock_search(name):
        yield "stable", [pkg]
        yield "unstable", []

    with patch("main.search", side_effect=mock_search), \
         patch("main.show_searching"), patch("main.show_done"), \
         patch("main.show_source_select", return_value=1), \
         patch("main.show_results", return_value=[pkg]), \
         patch("main.show_summary", return_value=True), \
         patch("main.add_package", return_value=AddResult(
             content=SYS, status="error", error="RuntimeError('boom')")), \
         patch("main.backup_files"), \
         patch("main.show_error") as mock_show:
        main_mod.handle_install("vim", config)

    assert mock_show.called
    assert "boom" in str(mock_show.call_args)


# ── rollback paths ──────────────────────────────────────────────────────────

def test_install_rollback_failure_is_reported():
    """A failed rebuild whose rollback also fails must show BOTH failures."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_nix = Path(tmpdir) / "configuration.nix"
        config_nix.write_text(SYS)
        config = {"setup": {"configuration_path": str(config_nix),
                            "flake_enabled": False}}

        pkg = MagicMock()
        pkg.name = "vim"
        pkg.attribute = "vim"
        pkg.source = "stable"
        pkg.version = "9.0"

        def mock_search(name):
            yield "stable", [pkg]
            yield "unstable", []

        with patch("main.search", side_effect=mock_search), \
             patch("main.show_searching"), patch("main.show_done"), \
             patch("main.show_source_select", return_value=1), \
             patch("main.show_results", return_value=[pkg]), \
             patch("main.show_summary", return_value=True), \
             patch("main.subprocess.run") as mock_run, \
             patch("main.backup_files"), \
             patch("main.restore_files", side_effect=OSError("cannot restore")), \
             patch("main.show_error") as mock_show:
            mock_run.return_value = MagicMock(returncode=1)
            main_mod.handle_install("vim", config)

    assert mock_show.called
    assert "rollback failed" in str(mock_show.call_args)
    assert "cannot restore" in str(mock_show.call_args)


def test_remove_rollback_failure_is_reported(tmp_path):
    config_nix = tmp_path / "configuration.nix"
    config_nix.write_text(SYS)
    config = {"setup": {"configuration_path": str(config_nix),
                        "flake_enabled": False}}

    with patch("main.subprocess.run") as mock_run, \
         patch("main.backup_files"), \
         patch("main.restore_files", side_effect=OSError("cannot restore")), \
         patch("builtins.input", return_value="y"), \
         patch("main.show_error") as mock_show:
        mock_run.return_value = MagicMock(returncode=1)
        main_mod.handle_remove("git", config)

    assert mock_show.called
    assert "rollback failed" in str(mock_show.call_args)
    assert "cannot restore" in str(mock_show.call_args)


def _install_flake_reference(tmp_path):
    """Create an nx-managed flake input and a matching package reference."""
    flake = Path(tmp_path, "flake.nix")
    config = Path(tmp_path, "configuration.nix")
    flake_content, target_content, status = add_flake(
        flake_content=flake.read_text(),
        flake_name="repo",
        flake_url="github:test/repo",
        pkg_attr="default",
        pkg_type="package",
        home_content=config.read_text(),
        block=SYSTEM_BLOCK,
    )
    assert status == "success", status
    assert isinstance(target_content, str)
    flake.write_text(flake_content)
    config.write_text(target_content)


def test_flakes_remove_rollback_failure_is_reported(tmp_path):
    Path(tmp_path, "flake.nix").write_text(FLAKE)
    Path(tmp_path, "configuration.nix").write_text(SYS)
    _install_flake_reference(tmp_path)
    config = _config(tmp_path)

    with patch("main.subprocess.run") as mock_run, \
         patch("main.backup_files"), \
         patch("main.restore_files", side_effect=OSError("cannot restore")), \
         patch("main.show_error") as mock_show:
        mock_run.return_value = MagicMock(returncode=1)
        main_mod.handle_flakes_remove("repo", config)

    assert mock_show.called
    assert "rollback failed" in str(mock_show.call_args)
    assert "cannot restore" in str(mock_show.call_args)


def test_flakes_remove_write_failure_is_reported(tmp_path):
    Path(tmp_path, "flake.nix").write_text(FLAKE)
    Path(tmp_path, "configuration.nix").write_text(SYS)
    _install_flake_reference(tmp_path)
    config = _config(tmp_path)

    with patch("main.subprocess.run") as mock_run, \
         patch("main.backup_files"), \
         patch("main.restore_files"), \
         patch("pathlib.Path.write_text", side_effect=OSError("read-only fs")), \
         patch("main.show_error") as mock_show:
        mock_run.return_value = MagicMock(returncode=0)
        main_mod.handle_flakes_remove("repo", config)

    assert mock_show.called
    assert "transaction failed during write" in str(mock_show.call_args)
    assert "read-only fs" in str(mock_show.call_args)
