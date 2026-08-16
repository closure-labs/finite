{inputs, ...}: let
  system = "x86_64-linux";
  pkgs = import inputs.nixpkgs {inherit system;};
in {
  flake.packages.${system} = {
    inherit (pkgs) sbomnix syft;
  };
}
