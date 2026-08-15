{
  description = "Purplefin bootc profile and user-environment configuration";

  inputs = {
    den.url = "github:denful/den";

    import-tree.url = "github:vic/import-tree";

    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  # Den's minimal dendritic entrypoint: feature/profile aspects and output
  # definitions are discovered as independent flake modules.
  outputs = inputs:
    (inputs.nixpkgs.lib.evalModules {
      specialArgs = {inherit inputs;};
      modules = [(inputs.import-tree ./nix/flake-modules)];
    }).config.flake;
}
