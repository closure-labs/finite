{
  description = "Purplefin bootc profile and user-environment configuration";

  nixConfig = {
    extra-substituters = [
      "https://purplefin.cachix.org"
      "https://devenv.cachix.org"
    ];
    extra-trusted-public-keys = [
      "purplefin.cachix.org-1:aW23hpySzX8WPYCiZSzxEc9mOYTIV9NDvylhqVgziFM="
      "devenv.cachix.org-1:w1cLUi8dv3hnoSPGAuibQv+f9TZLr6cv/Hm9XgU50cw="
    ];
  };

  inputs = {
    den.url = "github:denful/den";

    devenv.url = "github:cachix/devenv/v2.2.2";

    den-diagram = {
      url = "github:denful/den-diagram";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    import-tree.url = "github:vic/import-tree";

    nixpkgs.url = "https://flakehub.com/f/DeterminateSystems/nixpkgs-weekly/0";

    home-manager = {
      url = "https://flakehub.com/f/nix-community/home-manager/0";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    determinate.url = "https://flakehub.com/f/DeterminateSystems/determinate/3";

    nixgl = {
      url = "github:nix-community/nixGL";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    nix-flatpak.url = "github:gmodena/nix-flatpak";

    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  # Den's minimal dendritic entrypoint: feature/profile aspects and output
  # definitions are discovered as independent flake modules.
  outputs = inputs:
    (inputs.nixpkgs.lib.evalModules {
      specialArgs = {inherit inputs;};
      modules = [(inputs.import-tree ./modules)];
    }).config.flake;
}
