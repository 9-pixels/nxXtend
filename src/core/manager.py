from src.api.stable import stable_search
from src.api.unstable import unstable_search
from src.api.flakes import flake_search as _flake_search, flake_get_info as _flake_get_info

def deduplicate(packages):
    seen = set()
    result = []
    for pkg in packages:
        if pkg.name not in seen:
            seen.add(pkg.name)
            result.append(pkg)
    return result

def search(pkg_name: str):
    stable = deduplicate(stable_search(pkg_name))
    yield "stable", stable
    unstable = deduplicate(unstable_search(pkg_name))
    yield "unstable", unstable

def flake_search(flake_url: str):
    return _flake_search(flake_url)

def flake_get_info(flake_url: str, pkg_attr: str) -> dict:
    return _flake_get_info(flake_url, pkg_attr)