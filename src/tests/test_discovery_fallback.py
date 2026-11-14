"""Fallback discovery — when `nix flake show` fails, evaluate this system only.

`nix flake show` forces every output for every system a flake defines, so a
flake with one broken output for another system fails wholesale. The fallback
queries each output type for the current system individually, skips output
values that fail to evaluate, and never parses Nix error text to tell an
absent output type from a broken one.

Unit tests mock every nix invocation; the integration tests run real nix
against throwaway flakes in tmp directories and change nothing on the system.
"""
import json
import shutil
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from flakes.discovery import (
    _ProbeResult,
    _discover_current_system,
    _outputs_from_data,
    _probe_output_type,
    _report_probe_failures,
    _root_cause,
    discover,
)
from flakes.models import FlakeSource


def _completed(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def _names(payload):
    return _completed(0, json.dumps(payload), "")


# ── _outputs_from_data: the normal path's parsing ───────────────────────────

@pytest.mark.parametrize("payload,system,expected", [
    ({"packages": {"x86_64-linux": {"default": {}, "vim": {}}}},
     "x86_64-linux", [("packages", "default"), ("packages", "vim")]),
    ({"packages": {"aarch64-darwin": {"vim": {}}}},
     "x86_64-linux", []),
    ({"packages": {"x86_64-linux": "not-a-dict"}},
     "x86_64-linux", []),
    ({"packages": "not-a-dict"},
     "x86_64-linux", []),
    ({"hydraJobs": {"x86_64-linux": {"x": {}}}},
     "x86_64-linux", []),
    ({}, "x86_64-linux", []),
    ({"packages": {"x86_64-linux": {}}, "overlays": {"default": {}}},
     "x86_64-linux", [("overlays", "default")]),
], ids=[
    "default ordered first",
    "wrong system excluded",
    "non-dict system content skipped",
    "non-dict type content skipped",
    "unknown type ignored",
    "empty data",
    "empty system dict + overlay",
])
def test_outputs_from_data(payload, system, expected):
    outs = _outputs_from_data(payload, system)
    assert [(o.type, o.name) for o in outs] == expected


def test_outputs_from_data_attribute_paths():
    outs = _outputs_from_data(
        {"packages": {"x86_64-linux": {"vim": {}}}, "overlays": {"default": {}}},
        "x86_64-linux",
    )
    attrs = {o.name: o.attribute for o in outs}
    assert attrs["vim"] == "packages.x86_64-linux.vim"
    assert attrs["default"] == "overlays.default"


# ── _probe_output_type ──────────────────────────────────────────────────────

def test_probe_returns_names_for_a_present_type():
    with patch("flakes.discovery.subprocess.run", return_value=_names(["vim"])):
        probe = _probe_output_type("github:x/y", "packages.x86_64-linux")
    assert probe.names == ["vim"]
    assert probe.error is None
    assert probe.timed_out is False


def test_probe_absent_type_is_an_empty_list_not_an_error():
    """A flake without that output type is normal and must not be reported."""
    with patch("flakes.discovery.subprocess.run", return_value=_names([])):
        probe = _probe_output_type("github:x/y", "packages.x86_64-linux")
    assert probe.names == []
    assert probe.error is None


def test_probe_reports_a_genuine_command_failure():
    with patch("flakes.discovery.subprocess.run",
               return_value=_completed(1, "", "error: unable to download")):
        probe = _probe_output_type("github:x/y", "packages.x86_64-linux")
    assert probe.names is None
    assert "unable to download" in probe.error


def test_probe_reports_a_timeout():
    with patch("flakes.discovery.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd="nix", timeout=300)):
        probe = _probe_output_type("github:x/y", "packages.x86_64-linux")
    assert probe.names is None
    assert probe.timed_out is True
    assert "timed out" in probe.error


def test_probe_reports_invalid_json():
    with patch("flakes.discovery.subprocess.run",
               return_value=_completed(0, "{bad", "")):
        probe = _probe_output_type("github:x/y", "packages.x86_64-linux")
    assert probe.names is None
    assert probe.error


def test_probe_does_not_parse_nix_error_text():
    """Absence is expressed by `or {}`, not by matching an error string."""
    with patch("flakes.discovery.subprocess.run") as mr:
        mr.return_value = _names([])
        _probe_output_type("github:x/y", "packages.x86_64-linux")
    expr = mr.call_args[0][0][-1]
    assert "getFlake" in expr
    assert " or {}" in expr
    assert "does not provide attribute" not in expr


def test_probe_quotes_the_url_safely():
    with patch("flakes.discovery.subprocess.run") as mr:
        mr.return_value = _names([])
        _probe_output_type('github:x/y"tricky', "packages.x86_64-linux")
    expr = mr.call_args[0][0][-1]
    assert '\\"' in expr
    assert "${" not in expr.split("getFlake", 1)[1].split(";", 1)[0]


def test_probe_scopes_the_requested_attribute():
    with patch("flakes.discovery.subprocess.run") as mr:
        mr.return_value = _names(["vim"])
        _probe_output_type("github:x/y", "packages.aarch64-linux")
    expr = mr.call_args[0][0][-1]
    assert "f.packages.aarch64-linux" in expr


# ── _root_cause ─────────────────────────────────────────────────────────────

def test_root_cause_takes_the_last_error_line():
    report = "error:\n  while calling x\nerror: the real cause\nerror: final cause"
    assert _root_cause(report) == "error: final cause"


def test_root_cause_falls_back_to_the_last_non_empty_line():
    assert _root_cause("some failure\n  more detail") == "more detail"
    assert _root_cause("") == ""


# ── _report_probe_failures ──────────────────────────────────────────────────

def test_report_collapses_identical_failures_into_one_block(capsys):
    err = "error:\n  noise\nerror: unable to download"
    _report_probe_failures("github:x/y", [
        _ProbeResult(error=err), _ProbeResult(error=err),
    ])
    out = capsys.readouterr().out
    assert out.count("✗") == 1
    assert "2 output type(s)" in out
    assert "unable to download" in out


def test_report_keeps_full_output_of_the_first_failure(capsys):
    err = "error:\n  while evaluating\nerror: deliberate eval failure"
    _report_probe_failures("github:x/y", [_ProbeResult(error=err)])
    out = capsys.readouterr().out
    assert "while evaluating" in out
    assert "deliberate eval failure" in out


def test_report_keeps_full_output_of_every_distinct_cause(capsys):
    """A second root cause must not lose its diagnostic detail."""
    _report_probe_failures("github:x/y", [
        _ProbeResult(error="error:\n  while fetching A\nerror: cause A"),
        _ProbeResult(error="error:\n  while fetching B\nerror: cause B"),
    ])
    out = capsys.readouterr().out
    assert out.count("✗") == 1
    assert "1 type(s) failed with: error: cause A" in out
    assert "1 type(s) failed with: error: cause B" in out
    assert "while fetching A" in out
    assert "while fetching B" in out


def test_report_counts_match_the_number_of_failures(capsys):
    _report_probe_failures("github:x/y", [
        _ProbeResult(error="error: same cause"),
        _ProbeResult(error="error: same cause"),
        _ProbeResult(error="error: other cause"),
    ])
    out = capsys.readouterr().out
    assert "3 output type(s)" in out
    assert "2 type(s) failed with: error: same cause" in out
    assert "1 type(s) failed with: error: other cause" in out


def test_report_is_silent_without_failures(capsys):
    _report_probe_failures("github:x/y", [])
    assert capsys.readouterr().out == ""


# ── _discover_current_system ────────────────────────────────────────────────

def test_discover_current_system_orders_default_first():
    with patch("flakes.discovery._probe_output_type",
               side_effect=[_ProbeResult(names=["htop", "default"]),
                            _ProbeResult(names=[]), _ProbeResult(names=[]),
                            _ProbeResult(names=[]), _ProbeResult(names=[]),
                            _ProbeResult(names=[]),
                            _ProbeResult(names=["default", "extra"])]):
        outs = _discover_current_system(FlakeSource(url="github:x/y"), "x86_64-linux")
    assert [(o.type, o.name) for o in outs] == [
        ("packages", "default"), ("packages", "htop"),
        ("overlays", "default"), ("overlays", "extra"),
    ]


def test_discover_current_system_treats_absent_types_as_success():
    """Seven absent types must not produce a single error block."""
    with patch("flakes.discovery._probe_output_type", return_value=_ProbeResult(names=[])), \
         patch("flakes.discovery.show_error") as mock_show:
        outs = _discover_current_system(FlakeSource(url="github:x/y"), "x86_64-linux")
    assert outs == []
    assert not mock_show.called


def test_discover_current_system_stops_after_a_timeout():
    with patch("flakes.discovery._probe_output_type",
               side_effect=[_ProbeResult(names=None, error="timed out", timed_out=True),
                            _ProbeResult(names=["vim"])]) as mock_probe, \
         patch("flakes.discovery.show_error"):
        outs = _discover_current_system(FlakeSource(url="github:x/y"), "x86_64-linux")
    assert mock_probe.call_count == 1, "must not keep probing after a timeout"
    assert outs == []


def test_discover_current_system_reports_failures_once():
    with patch("flakes.discovery._probe_output_type",
               side_effect=lambda *a, **k: _ProbeResult(
                   names=None, error="error: unable to download")), \
         patch("flakes.discovery.show_error") as mock_show:
        _discover_current_system(FlakeSource(url="github:x/y"), "x86_64-linux")
    assert mock_show.call_count == 1


# ── discover: fallback wiring ───────────────────────────────────────────────

def test_discover_falls_back_when_show_fails():
    def probe(url, attr):
        if attr.startswith("packages"):
            return _ProbeResult(names=["default", "vim"])
        return _ProbeResult(names=[])

    with patch("flakes.discovery.subprocess.run",
               return_value=_completed(1, "", "error: broken darwin output")), \
         patch("flakes.discovery.get_current_system", return_value="x86_64-linux"), \
         patch("flakes.discovery._probe_output_type", side_effect=probe) as mock_probe:
        outs = discover(FlakeSource(url="github:x/y"))
    assert [(o.type, o.name) for o in outs] == [
        ("packages", "default"), ("packages", "vim"),
    ]
    assert mock_probe.call_count == 7


def test_discover_does_not_fall_back_after_a_timeout():
    with patch("flakes.discovery.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd="nix", timeout=120)), \
         patch("flakes.discovery._probe_output_type") as mock_probe, \
         patch("flakes.discovery.show_error") as mock_show:
        outs = discover(FlakeSource(url="github:x/y"))
    assert outs == []
    assert not mock_probe.called, "fallback must not run after a timeout"
    assert mock_show.called
    assert "timed out" in str(mock_show.call_args)


def test_discover_reports_empty_show_output():
    with patch("flakes.discovery.subprocess.run", return_value=_completed(0, "", "")), \
         patch("flakes.discovery.show_error") as mock_show:
        assert discover(FlakeSource(url="github:x/y")) == []
    assert mock_show.called


def test_discover_reports_when_no_supported_outputs():
    payload = json.dumps({"hydraJobs": {"x86_64-linux": {"x": {}}}})
    with patch("flakes.discovery.subprocess.run", return_value=_completed(0, payload, "")), \
         patch("flakes.discovery.get_current_system", return_value="x86_64-linux"), \
         patch("flakes.discovery.show_error") as mock_show:
        outs = discover(FlakeSource(url="github:x/y"))
    assert outs == []
    assert mock_show.called


def test_discover_fallback_is_not_used_when_show_succeeds():
    payload = json.dumps({"packages": {"x86_64-linux": {"vim": {}}}})
    with patch("flakes.discovery.subprocess.run") as mr, \
         patch("flakes.discovery.get_current_system", return_value="x86_64-linux"), \
         patch("flakes.discovery._probe_output_type") as mock_probe:
        mr.return_value = _completed(0, payload, "")
        outs = discover(FlakeSource(url="github:x/y"))
    assert mr.call_count == 1, "fallback must not run when `flake show` succeeds"
    assert not mock_probe.called
    assert [(o.type, o.name) for o in outs] == [("packages", "vim")]


# ── integration: real nix against throwaway flakes ──────────────────────────

requires_nix = pytest.mark.skipif(shutil.which("nix") is None, reason="nix is not available")


def _system() -> str:
    out = subprocess.run(
        ["nix", "eval", "--impure", "--expr", "builtins.currentSystem", "--raw"],
        capture_output=True, text=True, timeout=60,
    )
    return out.stdout.strip()


def _flake(body: str) -> str:
    return "{\n  outputs = { self }: {\n" + body + "\n  };\n}\n"


def _derivation(name: str, system: str) -> str:
    return ('derivation {\n'
            f'      name = "{name}"; system = "{system}"; builder = "/bin/sh";\n'
            '      args = [ "-c" "echo hi > $out" ];\n'
            '    }')


@requires_nix
class TestRealNixDiscovery:
    """These exercise real nix; they write only inside tmp_path."""

    def test_broken_output_is_not_offered(self, tmp_path):
        system = _system()
        (tmp_path / "flake.nix").write_text(_flake(
            f"    packages.{system}.good = {_derivation('good', system)};\n"
            f'    packages.{system}.bad = throw "deliberate eval failure";\n'
        ))
        outs = discover(FlakeSource(url=str(tmp_path)))
        names = [o.name for o in outs]
        assert "good" in names, f"healthy output missing: {names}"
        assert "bad" not in names, f"broken output was offered: {names}"

    def test_healthy_flake_still_discovers_everything(self, tmp_path):
        system = _system()
        (tmp_path / "flake.nix").write_text(_flake(
            f"    packages.{system}.default = {_derivation('d', system)};\n"
            "    overlays.default = final: prev: { };\n"
            "    nixosModules.default = { config, ... }: { };\n"
        ))
        outs = discover(FlakeSource(url=str(tmp_path)))
        assert [(o.type, o.name) for o in outs] == [
            ("packages", "default"),
            ("nixosModules", "default"),
            ("overlays", "default"),
        ]

    def test_absent_types_produce_no_probe_error(self, tmp_path):
        (tmp_path / "flake.nix").write_text('{ outputs = { self }: { }; }\n')
        with patch("flakes.discovery.show_error") as mock_show:
            outs = discover(FlakeSource(url=str(tmp_path)))
        assert outs == []
        for call in mock_show.call_args_list:
            assert "could not query" not in str(call), (
                "an absent output type must not be reported as a failure"
            )
