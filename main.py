from src.api.flakes import flake_search

results = flake_search("github:Ayman-pixels-33/nix-test")
for pkg in results:
    print(pkg.name, pkg.version, pkg.description)