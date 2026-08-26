{
  description = "Finite bootc profile and user-environment configuration";

  # Consumers derive the Finite cache name from this centralized URL.
  # Flake configuration rejects imported values as thunks. Project evaluation
  # consumes lib/project-policy.nix directly, and repository checks keep this
  # required concrete copy synchronized with that policy.
  nixConfig = {
    extra-substituters = [
      "https://finite-os.cachix.org"
      "https://devenv.cachix.org"
      "https://cachix.cachix.org"
    ];
    extra-trusted-public-keys = [
      "finite-os.cachix.org-1:iwOc148wD1hSWnyNwhP3DsMxBv8WcL+ppMwcRIvx4Ko="
      "devenv.cachix.org-1:w1cLUi8dv3hnoSPGAuibQv+f9TZLr6cv/Hm9XgU50cw="
      "cachix.cachix.org-1:eWNHQldwUO7G2VkjpnjDbWwy4KQ/HNxht7H4SSoMckM="
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
