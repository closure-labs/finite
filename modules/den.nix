{inputs, ...}: let
  catalog = import ../lib/domain-catalog.nix {homeCatalog = inputs.foundation.lib.catalog;};
  project = import ../lib/project-policy.nix;
  system = project.platform.system;
  mkPkgs = import ../lib/mk-pkgs.nix {inherit (inputs) nixpkgs;};
  outputDependencies = {
    inherit (inputs) foundation;
    inherit (inputs) self;
    denFlakeModule = inputs.den.flakeModule;
    treefmt = inputs.treefmt-nix.lib;
    devenvPackage = inputs.devenv.packages.${system}.devenv;
  };
in {
  imports = [outputDependencies.denFlakeModule inputs.foundation.flakeModules.aspects];

  _module.args = {
    inherit catalog mkPkgs outputDependencies project;
  };
}
