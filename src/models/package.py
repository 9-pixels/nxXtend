from dataclasses import dataclass

@dataclass
class Package:
    name: str
    version: str | None
    description: str | None
    source: str
    type: str | None
    attribute: str | None
    install_type: str | None = None