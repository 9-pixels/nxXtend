from src.flakes.models import FlakeSource
import subprocess
import json

def parse_flake_url(url: str) -> FlakeSource:
    if "#" in url:
        base, target = url.split("#", 1)
        return FlakeSource(url=base, target=target)
    return FlakeSource(url=url)

def get_metadata(source: FlakeSource) -> FlakeSource:
    result = subprocess.run(
        ["nix", "flake", "metadata", "--json", source.url],
        capture_output=True,
        text=True,
        timeout=60
    )
    if result.returncode != 0 or not result.stdout.strip():
        return source
    data = json.loads(result.stdout)
    locked = data.get("locked") or {}
    revision = locked.get("rev")
    return FlakeSource(url=source.url, target=source.target, revision=revision)