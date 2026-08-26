{lib, ...}: let
  flakeConfig = (import ./flake.nix).nixConfig;
  cacheUrl = builtins.head flakeConfig.extra-substituters;
  cacheName = lib.removeSuffix ".cachix.org" (lib.removePrefix "https://" cacheUrl);
in {
  imports = [./devenv-tasks.nix];

  cachix.pull = ["cachix" cacheName];
}
