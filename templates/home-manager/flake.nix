{
  description = "Finite standalone Home Manager configuration";

  inputs = {
    den.url = "github:denful/den";
    devenv.url = "github:cachix/devenv/v2.2.2";
    nixpkgs.url = "https://flakehub.com/f/DeterminateSystems/nixpkgs-26.05-chilled/0.1";
    nixpkgs-weekly.url = "https://flakehub.com/f/DeterminateSystems/nixpkgs-weekly/0.1";
    home-manager = {
      url = "https://flakehub.com/f/nix-community/home-manager/0.2605";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    determinate.url = "https://flakehub.com/f/DeterminateSystems/determinate/3";
    nixgl = {
      url = "github:nix-community/nixGL";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    nix-flatpak.url = "github:gmodena/nix-flatpak";
  };

  outputs = inputs:
    (inputs.nixpkgs.lib.evalModules {
      specialArgs = {inherit inputs;};
      modules = [
        inputs.den.flakeModule
        ./modules/finite.nix
      ];
    }).config.flake;
}
