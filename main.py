from src.api.flakes import flake_search

results = flake_search("github:9-pixels/nix-test")
for pkg in results:
    print(pkg.name, pkg.version, pkg.description)