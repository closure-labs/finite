{
  den,
  lib,
  ...
}: let
  inherit (den.aspects) features;

  definitions = {
    base = {
      includes = [features.base];
      tags = ["base"];
    };

    base-generic = {
      parent = "base";
      includes = [features.hardware-generic-x86_64];
      tags = [
        "generic-x86_64"
        "latest"
        "base-generic-x86_64"
      ];
    };

    base-dell-xps-9350-intel = {
      parent = "base";
      includes = [features.hardware-dell-xps-9350-intel];
      tags = ["base-dell-xps-9350-intel"];
    };

    sales-generic = {
      parent = "base-generic";
      includes = [features.sales];
      tags = ["sales-generic"];
    };

    sales-dell-xps-9350-intel = {
      parent = "base-dell-xps-9350-intel";
      includes = [features.sales];
      tags = ["sales-dell-xps-9350-intel"];
    };

    support-generic = {
      parent = "base-generic";
      includes = [features.support];
      tags = ["support-generic"];
    };

    support-dell-xps-9350-intel = {
      parent = "base-dell-xps-9350-intel";
      includes = [features.support];
      tags = ["support-dell-xps-9350-intel"];
    };

    dale = {
      parent = "base-dell-xps-9350-intel";
      includes = [
        features.sales
        features.trainer
        features.support
      ];
      tags = [
        "dale"
        "dell-xps-9350-intel"
      ];
    };

    developer-generic = {
      parent = "base-generic";
      includes = [features.developer];
      tags = ["developer-generic"];
    };

    trainer-generic = {
      parent = "base-generic";
      includes = [features.trainer];
      tags = ["trainer-generic"];
    };

    executive-generic = {
      parent = "base-generic";
      includes = [features.executive];
      tags = ["executive-generic"];
    };

    it-generic = {
      parent = "base-generic";
      includes = [features.it];
      tags = ["it-generic"];
    };
  };

  profileStacks =
    lib.mapAttrs (
      name: definition: let
        parent = definition.parent or null;
        inherited =
          if parent == null
          then []
          else [
            (den.aspects.profile-stacks.${parent}
              or (throw "Purplefin profile error: ${name} has unknown parent ${parent}"))
          ];
      in {
        includes = inherited ++ definition.includes;
      }
    )
    definitions;

  profiles =
    lib.mapAttrs (
      name: definition: let
        parent = definition.parent or null;
      in {
        includes = [den.aspects.profile-stacks.${name}];
        bootc.purplefin = {
          profileName = name;
          inherit parent;
          tags = definition.tags;
        };
      }
    )
    definitions;
in {
  den.aspects.profile-stacks = profileStacks;
  den.aspects.profiles = profiles;
}
