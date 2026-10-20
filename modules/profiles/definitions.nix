{
  catalog,
  den,
  lib,
  ...
}: let
  inherit (den.aspects) features;
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
      inherit (catalog.hardwareByName.${name}) imageHardware label;
      aspect = features.hardware.${name};
    }
  );
  roles =
    lib.mapAttrs (
      name: role: {
        inherit (role) label order;
        classification = role.classification or null;
        aspect = features.roles.${name};
      }
    )
    catalog.rolesByName;
  packages =
    lib.mapAttrs (
      _: package: {
        inherit (package) description label order;
      }
    )
    catalog.packagesByName;
in {
  finite.home = {
    inherit foundations hardware packages roles;
    classifications = lib.mapAttrs (name: classification: {
      inherit (classification) name label order;
      roles = builtins.sort (a: b:
        if roles.${a}.order == roles.${b}.order
        then a < b
        else roles.${a}.order < roles.${b}.order)
      (builtins.filter (role: roles.${role}.classification == name) catalog.roleNames);
    }) (catalog.classificationsByName or {});
  };
}
