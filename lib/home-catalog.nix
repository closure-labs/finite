{
  domainCatalog,
  lib,
  version,
}: let
  inherit (domainCatalog) packageNames roleNames;
in {
  schema = 3;
  inherit version;
  foundations =
    lib.mapAttrs (
      _: foundation: {
        inherit (foundation) name template;
        profiles = lib.mapAttrs (_: profile: profile.name) foundation.profiles;
        hardware = domainCatalog.homeHardwareNames;
        packages = packageNames;
        roles = roleNames;
      }
    )
    domainCatalog.foundationsByName;
  hardware = lib.genAttrs domainCatalog.homeHardwareNames (
    name: {
      inherit (domainCatalog.hardwareByName.${name}) imageHardware label name;
    }
  );
  roles =
    lib.mapAttrs (
      _: role: {
        inherit (role) label name order;
        foundations = domainCatalog.foundationNames;
      }
    )
    domainCatalog.rolesByName;
  packages =
    lib.mapAttrs (
      _: package: {
        inherit (package) description label name order;
        foundations = domainCatalog.foundationNames;
      }
    )
    domainCatalog.packagesByName;
  compatibility =
    lib.mapAttrs (_: _foundation: {
      hardware = domainCatalog.homeHardwareNames;
      packages = packageNames;
      roles = roleNames;
    })
    domainCatalog.foundationsByName;
}
