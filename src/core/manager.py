from src.api.stable import stable_search
from src.api.unstable import unstable_search
from src.api.flakes import flake_search


def flake_install(flake_url: str):
    return flake_search(flake_url)

def deduplicate(packages):
    seen = set()
    result = []
    for pkg in packages:
        if pkg.name not in seen:
            seen.add(pkg.name)
            result.append(pkg)
    return result

def search(pkg_name: str):
    stable_results = deduplicate(stable_search(pkg_name))
    unstable_results = deduplicate(unstable_search(pkg_name))
    return stable_results, unstable_results