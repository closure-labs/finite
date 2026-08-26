{
  catalog,
  den,
  lib,
  ...
}: let
  inherit (den.aspects) features;
  profileAspects =
    lib.mapAttrs (
      _: profile: {
        includes = [
          features.base
          features.upstreams.${profile.foundation}
          features.hardware.${profile.hardware}
        ];
      }
    )
    catalog.profilesByName;
  profileEntities =
    lib.mapAttrs (
      _: profile: {
        inherit (profile) parent tags;
      }
    )
    catalog.profilesByName;
  foundations =
    lib.mapAttrs (
      _: foundation: {
        inherit (foundation) template;
        profiles = lib.mapAttrs (_: profile: profile.name) foundation.profiles;
      }
    )
    catalog.foundationsByName;
  hardware = lib.genAttrs catalog.homeHardwareNames (
    name: {
      inherit (catalog.hardwareByName.${name}) label;
      aspect = features.hardware.${name};
    }
  );
  roles =
    lib.mapAttrs (
      name: role: {
        inherit (role) label order;
        aspect = features.roles.${name};
      }
    )
    catalog.rolesByName;
in {
  den.aspects.profiles = profileAspects;

  finite.profiles = profileEntities;

  finite.home = {
    inherit foundations hardware roles;
  };
}
