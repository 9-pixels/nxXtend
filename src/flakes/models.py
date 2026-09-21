from dataclasses import dataclass


@dataclass
class FlakeSource:
    url: str
    revision: str | None = None
    target: str | None = None


@dataclass
class FlakeOutput:
    name: str
    type: str
    system: str | None = None
    attribute: str | None = None
    description: str | None = None


@dataclass
class InstallationPlan:
    source: FlakeSource
    output: FlakeOutput
    action: str
    system: str
    flake_name: str