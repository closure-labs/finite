{inputs, ...}: let
  catalog = import ../lib/domain-catalog.nix;
  project = import ../lib/project-policy.nix;
  system = project.platform.system;
  mkPkgs = import ../lib/mk-pkgs.nix {inherit (inputs) nixpkgs;};
  homeDependencies = {
    determinateModule = inputs.determinate.homeManagerModules.default;
    flatpakModule = inputs.nix-flatpak.homeManagerModules.nix-flatpak;
    nixglPackages = inputs.nixgl.packages.${system};
    weeklyPackages = inputs.nixpkgs-weekly.legacyPackages.${system};
    devenvPackage = inputs.devenv.packages.${system}.devenv;
  };
  outputDependencies = {
    inherit (inputs) self;
    denFlakeModule = inputs.den.flakeModule;
    diagram = inputs.den-diagram.lib;
    homeManagerLib = inputs.home-manager.lib;
    homeModuleInputs = {
      inherit (inputs) den home-manager nixpkgs;
    };
    treefmt = inputs.treefmt-nix.lib;
    weeklySecretspec = homeDependencies.weeklyPackages.secretspec;
    inherit (homeDependencies) devenvPackage;
  };
in {
  imports = [outputDependencies.denFlakeModule];

  _module.args = {
    inherit catalog homeDependencies mkPkgs outputDependencies project;
  };

  den.classes.bootc.description = "Finite bootc image composition";
}
