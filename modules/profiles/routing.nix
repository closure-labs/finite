{
  config,
  den,
  lib,
  ...
}: let
  inherit (den.lib.policy) resolve;
  profiles = config.purplefin.profiles;
in {
  den = {
    policies.flake-to-profiles = _:
      lib.mapAttrsToList (
        _: profile: resolve.to "profile" {inherit profile;}
      )
      profiles;

    schema.flake.includes = [den.policies.flake-to-profiles];
    schema.profile.includes = [({profile, ...}: profile.aspect)];
  };
}
