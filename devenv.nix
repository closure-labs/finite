{lib, ...}: let
  flakeConfig = (import ./flake.nix).nixConfig;
  cacheUrl = builtins.head flakeConfig.extra-substituters;
  cacheName = lib.removeSuffix ".cachix.org" (lib.removePrefix "https://" cacheUrl);
in {
  imports = [./devenv-tasks.nix];

  # Explicit task profiles/scopes override user-global SecretSpec selections.
  # The default developer profile contains options and optional Cachix only.
  env.FINITE_SECRETS_PROVIDER = lib.mkDefault "local";

  cachix.pull = ["cachix" cacheName];
}
