{
  description = "nxXtend - NixOS package management automation tool";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];

      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs {
            inherit system;
          };
        in
        {
          default = pkgs.python3Packages.buildPythonApplication {
            pname = "nxXtend";
            version = "0.1.0";

            src = ./.;

            pyproject = true;

            build-system = [
              pkgs.python3Packages.setuptools
            ];

            dependencies = with pkgs.python3Packages; [
              requests
              rich
              toml
            ];
          };
        });

      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs {
            inherit system;
          };
        in
        {
          default = pkgs.mkShell {
            packages = [
              pkgs.python3
              pkgs.python3Packages.pytest
            ];
          };
        });
    };
}