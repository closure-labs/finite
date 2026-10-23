# Select the existing locked payload without composing Finite's Den outputs.
# Read inputs from the root flake so Foundation's full locked graph and follows
# remain identical to the public image-payload output.
{inputs ? (builtins.getFlake (toString ../.)).inputs}: let
  project = import ./project-policy.nix;
  pkgs = import ./mk-pkgs.nix {inherit (inputs) nixpkgs;} project.platform.system;
  lib = inputs.nixpkgs.lib;
  foundation = inputs.foundation;
  catalog = import ./domain-catalog.nix {homeCatalog = foundation.lib.catalog;};
  homeScaffold = import ./render-home-scaffold.nix {inherit pkgs foundation;};
  version = lib.removeSuffix "\n" (builtins.readFile ../VERSION);
in
  import ./image-payload.nix {
    inherit
      pkgs
      lib
      foundation
      catalog
      homeScaffold
      version
      ;
  }
