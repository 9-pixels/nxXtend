from src.api.stable import stable_search
from src.api.unstable import unstable_search
from src.api.flakes import flake_search

results = flake_search("github:caelestia-dots/shell", "caelestia")
for pkg in results:
    print(pkg.name, pkg.version, pkg.description)


