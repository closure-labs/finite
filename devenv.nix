{lib, ...}: let
  flakeConfig = (import ./flake.nix).nixConfig;
  legacyCacheUrl = builtins.head flakeConfig.extra-substituters;
  legacyCacheName = lib.removeSuffix ".cachix.org" (lib.removePrefix "https://" legacyCacheUrl);
in {
  imports = [./devenv-tasks.nix];

  cachix.pull = ["cachix" legacyCacheName];
}
