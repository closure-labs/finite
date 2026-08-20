{
  description = "Purplefin bootc profile and user-environment configuration";

  nixConfig = {
    extra-substituters = "https://purplefin.cachix.org";
    extra-trusted-public-keys = "purplefin.cachix.org-1:aW23hpySzX8WPYCiZSzxEc9mOYTIV9NDvylhqVgziFM=";
  };

  inputs = {
    den.url = "github:denful/den";

    den-diagram = {
      url = "github:denful/den-diagram";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    import-tree.url = "github:vic/import-tree";

    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    home-manager = {
      url = "github:nix-community/home-manager";
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
