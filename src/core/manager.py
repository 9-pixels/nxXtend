from src.api.stable import stable_search
from src.api.unstable import unstable_search
from src.api.flakes import flake_search

def search(pkg_name: str):
    stable_results = stable_search(pkg_name)
    unstable_results = unstable_search(pkg_name)
    return stable_results, unstable_results

def flake_install(flake_url: str):
    return flake_search(flake_url)