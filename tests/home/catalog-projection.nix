# Exercise the actual typed module boundary with current and legacy domains.
{
  lib,
  catalog,
}: let
  project = domain: let
    evaluated = lib.evalModules {
      specialArgs = {
        catalog = domain;
        den.aspects.features = {
          roles = lib.genAttrs domain.roleNames (name: {inherit name;});
          hardware = lib.genAttrs domain.homeHardwareNames (name: {inherit name;});
        };
      };
      modules = [../../modules/profiles/schema.nix ../../modules/profiles/definitions.nix];
    };
  in
    evaluated.config.finite.home;
  current = project catalog;
  legacy = project ((builtins.removeAttrs catalog ["classifications" "classificationsByName" "classificationNames"])
    // {
      rolesByName = lib.mapAttrs (_: role: builtins.removeAttrs role ["classification"]) catalog.rolesByName;
    });
  expectedGroups = lib.mapAttrs (name: classification: {
    inherit (classification) name label order;
    roles = builtins.sort (a: b:
      if catalog.rolesByName.${a}.order == catalog.rolesByName.${b}.order
      then a < b
      else catalog.rolesByName.${a}.order < catalog.rolesByName.${b}.order)
    (builtins.filter (role: (catalog.rolesByName.${role}.classification or null) == name) catalog.roleNames);
  }) (catalog.classificationsByName or {});
in
  assert current.classifications == expectedGroups;
  assert builtins.all (name: current.roles.${name}.classification == (catalog.rolesByName.${name}.classification or null)) catalog.roleNames;
  assert legacy.classifications == {};
  assert builtins.all (name: legacy.roles.${name}.classification == null) catalog.roleNames; true
