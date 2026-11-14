# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 9-pixels

import subprocess
import json
import platform
from dataclasses import dataclass
from flakes.models import FlakeSource, FlakeOutput
from ui.display import show_command_error, show_error, timeout_detail

SYSTEMIC_TYPES = {"packages", "legacyPackages", "apps", "devShells"}
NON_SYSTEMIC_TYPES = {"nixosModules", "homeManagerModules", "overlays"}
KNOWN_TYPES = SYSTEMIC_TYPES | NON_SYSTEMIC_TYPES

# The one canonical output-type order, shared by the `nix flake show` path and
# the fallback so a flake presents the same menu regardless of which path
# discovered it.
OUTPUT_TYPE_ORDER = (
    "packages", "legacyPackages", "apps", "devShells",
    "nixosModules", "homeManagerModules", "overlays",
)

_SHOW_TIMEOUT = 120
_PROBE_TIMEOUT = 300
_SYSTEM_TIMEOUT = 60


@dataclass
class _ProbeResult:
    """Outcome of probing one output type on one flake.

    ``names`` is ``None`` when the type could not be probed at all — the
    command failed, timed out, or returned something unusable. It is a list
    when the probe succeeded, and an empty list means the flake genuinely has
    no such output. That distinction is what keeps "not provided" from being
    reported as an error.
    """

    names: list[str] | None = None
    error: str | None = None
    timed_out: bool = False


def _nix_string(value: str) -> str:
    """Render a Python string as a Nix string literal."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("${", "\\${")
    return f'"{escaped}"'


def get_current_system() -> str:
    cmd = ["nix", "eval", "--impure", "--expr", "builtins.currentSystem", "--raw"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=_SYSTEM_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        show_error(
            f"nix eval timed out after {_SYSTEM_TIMEOUT}s while reading the "
            "current system",
            timeout_detail(exc, _SYSTEM_TIMEOUT) +
            "\n\nfalling back to the platform-reported system",
        )
    else:
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        show_command_error(cmd, result)

    # fallback
    machine = platform.machine()
    system = platform.system().lower()
    arch = "x86_64" if machine == "x86_64" else "aarch64"
    return f"{arch}-{system}"


def _move_default_first(outputs: list[FlakeOutput]) -> list[FlakeOutput]:
    """Put the conventional ``default`` output first, keeping the rest in order."""
    for i, out in enumerate(outputs):
        if out.name == "default":
            return [outputs[i]] + outputs[:i] + outputs[i+1:]
    return outputs


def _append_type(outputs: list[FlakeOutput], output_type: str,
                 names, system: str | None) -> None:
    """Append one output type's entries, ``default`` first."""
    type_outputs = [
        FlakeOutput(
            name=name,
            type=output_type,
            system=system,
            attribute=f"{output_type}.{system}.{name}" if system
                      else f"{output_type}.{name}",
        )
        for name in names
    ]
    outputs.extend(_move_default_first(type_outputs))


def _outputs_from_data(data: dict, system: str) -> list[FlakeOutput]:
    """Build FlakeOutput objects from `nix flake show --json` data.

    Types are visited in :data:`OUTPUT_TYPE_ORDER` rather than in the order the
    JSON happens to use, so this path and the fallback present the same menu.
    """
    outputs: list[FlakeOutput] = []
    for output_type in OUTPUT_TYPE_ORDER:
        content = data.get(output_type)
        if not isinstance(content, dict):
            continue

        if output_type in SYSTEMIC_TYPES:
            if system not in content:
                continue
            system_content = content[system]
            if not isinstance(system_content, dict):
                continue
            _append_type(outputs, output_type, list(system_content), system)
        else:
            _append_type(outputs, output_type, list(content), None)
    return outputs


def _probe_output_type(url: str, attr_path: str) -> _ProbeResult:
    """Probe one output type on one flake.

    ``builtins.getFlake`` is used instead of a ``flake#attrpath`` reference so
    that an output type the flake does not provide evaluates to ``{}`` rather
    than failing — no Nix error text has to be parsed to tell "absent" apart
    from "broken". Values that fail to evaluate are filtered out, so a broken
    output is never offered to the user as installable.
    """
    expr = (
        "let f = builtins.getFlake " + _nix_string(url) + "; "
        "xs = f." + attr_path + " or {}; "
        "in (builtins.partition (n: (builtins.tryEval xs.${n}).success) "
        "(builtins.attrNames xs)).right"
    )
    cmd = [
        "nix", "eval", "--json", "--impure",
        "--no-write-lock-file",
        "--no-accept-flake-config",
        "--expr", expr,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=_PROBE_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        return _ProbeResult(
            error=timeout_detail(exc, _PROBE_TIMEOUT), timed_out=True,
        )
    if result.returncode != 0:
        return _ProbeResult(error=(result.stderr or result.stdout or "").strip())
    try:
        names = json.loads(result.stdout)
    except json.JSONDecodeError:
        return _ProbeResult(
            error=f"invalid JSON from nix eval: {result.stdout[:200]!r}"
        )
    if not isinstance(names, list):
        return _ProbeResult(
            error=f"unexpected nix eval output: {result.stdout[:200]!r}"
        )
    return _ProbeResult(names=names)


def _root_cause(error: str) -> str:
    """Reduce a Nix error report to its final ``error:`` line.

    Every probe failure echoes the probe's own expression, so two failures
    with the same cause differ textually. The last ``error:`` line is the
    actual cause and is what makes failures groupable.
    """
    cause = ""
    for line in error.splitlines():
        stripped = line.strip()
        if stripped.startswith("error:"):
            cause = stripped
    if cause:
        return cause
    lines = [line.strip() for line in error.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _report_probe_failures(url: str, failures: list[_ProbeResult]) -> None:
    """Report probe failures once, with full detail, instead of one block each.

    All probes target the same flake, so a fetch or evaluation problem usually
    fails all of them. They are collapsed to a single block: one entry per
    distinct root cause with the number of types it affected and the complete
    output of that group's first failure, so no diagnostic detail is lost.
    """
    if not failures:
        return

    counts: dict[str, int] = {}
    first: dict[str, _ProbeResult] = {}
    for failure in failures:
        key = _root_cause(failure.error or "")
        counts[key] = counts.get(key, 0) + 1
        first.setdefault(key, failure)

    lines = [f"{len(failures)} output type(s) could not be queried for {url}."]

    for key, count in counts.items():
        lines.append("")
        lines.append(f"  {count} type(s) failed with: {key}")
        lines.append("    full output of the first failure in this group:")
        lines.extend(f"      {line}" for line in
                     (first[key].error or "").splitlines() or ["(none)"])

    show_error("could not query every output type", "\n".join(lines))


def _discover_current_system(source: FlakeSource, system: str) -> list[FlakeOutput]:
    """Fallback discovery: evaluate only the current system's outputs.

    `nix flake show` forces every output for every system the flake defines.
    A flake that ships a broken output for another system — a darwin devShell
    on a Linux machine, say — therefore fails wholesale even though this
    system's outputs are perfectly usable. This path queries each output type
    for this system only, so such flakes still install.

    Output types that fail to evaluate are skipped rather than offered, and a
    probe that times out stops the sweep instead of spending a full timeout on
    every remaining type.
    """
    outputs: list[FlakeOutput] = []
    failures: list[_ProbeResult] = []

    probes = [
        (output_type,
         f"{output_type}.{system}" if output_type in SYSTEMIC_TYPES else output_type,
         system if output_type in SYSTEMIC_TYPES else None)
        for output_type in OUTPUT_TYPE_ORDER
    ]
    for output_type, attr_path, out_system in probes:
        probe = _probe_output_type(source.url, attr_path)
        # An empty list is a successful probe of a type the flake does not
        # provide; only None means the type could not be queried at all.
        if probe.names is not None:
            _append_type(outputs, output_type, probe.names, out_system)
        else:
            failures.append(probe)
            if probe.timed_out:
                break

    _report_probe_failures(source.url, failures)
    return outputs


def discover(source: FlakeSource) -> list[FlakeOutput]:
    """Discover available outputs in a flake.

    This function calls `nix flake show --json` and parses the result into
    a structured list of FlakeOutput objects. It handles two categories:

    - Systemic types (packages, legacyPackages, apps, devShells): these are
      system-specific, so we filter by the current system.
    - Non-systemic types (nixosModules, homeManagerModules, overlays): these
      are system-agnostic.

    The `--no-write-lock-file` and `--no-accept-flake-config` flags are
    important: they prevent nix from modifying the local lock file or
    accepting config from the remote flake, which could otherwise change
    system state during discovery.

    When `nix flake show` fails outright, discovery falls back to evaluating
    this system's outputs individually — see :func:`_discover_current_system`.
    A timeout is reported and not retried, because the fallback would
    evaluate each output type separately and take at least as long.

    Every empty result is explained here, so callers do not need to add a
    second "no results" message of their own.
    """
    cmd = [
        "nix", "flake", "show", "--json",
        "--no-write-lock-file",
        "--no-accept-flake-config",
        source.url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=_SHOW_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        show_error(
            f"nix flake show timed out after {_SHOW_TIMEOUT}s for {source.url}",
            timeout_detail(exc, _SHOW_TIMEOUT) +
            "\n\nthe flake took too long to evaluate. The per-output-type "
            "fallback was not attempted, because it evaluates each type "
            "separately and would take at least as long.",
        )
        return []
    if result.returncode != 0:
        show_command_error(cmd, result)
        return _discover_current_system(source, get_current_system())
    if not result.stdout.strip():
        show_error(f"nix flake show produced no output for {source.url}")
        return []

    data = json.loads(result.stdout)
    outputs = _outputs_from_data(data, get_current_system())
    if not outputs:
        show_error(f"no supported outputs found in {source.url}")
    return outputs

INSTALLABLE = {"packages", "legacyPackages"}
CONFIGURABLE = {"nixosModules", "homeManagerModules"}
EXECUTABLE = {"apps"}
OVERLAY = {"overlays"}
UNSUPPORTED = {"devShells", "checks"}


def classify(output: FlakeOutput) -> str:
    if output.type in INSTALLABLE:
        return "installable"
    if output.type in CONFIGURABLE:
        return "configurable"
    if output.type in EXECUTABLE:
        return "executable"
    if output.type in OVERLAY:
        return "overlay"
    return "unsupported"
