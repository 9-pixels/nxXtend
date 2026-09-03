from src.api.stable import stable_search
from src.api.unstable import unstable_search
from src.api.flakes import flake_search

def deduplicate(packages):
    # Deduplicate by package name to avoid showing the same package twice
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

def search_flake(flake_url: str):
    return flake_search(flake_url)