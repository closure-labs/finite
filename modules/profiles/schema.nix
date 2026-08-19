{
  den,
  lib,
  ...
}: let
  profileType = lib.types.submodule (
    {name, ...}: {
      imports = [den.schema.profile];
      options = {
        name = lib.mkOption {
          type = lib.types.strMatching "[a-z0-9._-]+";
          default = name;
          description = "Published Purplefin profile identifier.";
        };

        parent = lib.mkOption {
          type = lib.types.nullOr (lib.types.strMatching "[a-z0-9._-]+");
          default = null;
          description = "Optional parent profile used for staged bootc builds.";
        };

        tags = lib.mkOption {
          type = lib.types.listOf (lib.types.strMatching "[a-z0-9._-]+");
          description = "Registry tags, with the canonical tag first.";
        };

        aspect = lib.mkOption {
          type = lib.types.raw;
          default = den.aspects.profiles.${name};
          defaultText = "den.aspects.profiles.<name>";
          description = "Den composition aspect for this profile entity.";
        };
      };
    }
  );
  homeProfileType = lib.types.submodule (
    {name, ...}: {
      options = {
        name = lib.mkOption {
          type = lib.types.strMatching "[a-z0-9._-]+";
          default = name;
          description = "Published Purplefin Home Manager profile identifier.";
        };
        baseClass = lib.mkOption {
          type = lib.types.enum ["bluefin" "bluefin-dx"];
          description = "Required upstream foundation class.";
        };
        hardware = lib.mkOption {
          type = lib.types.listOf (lib.types.enum ["generic-x86_64" "dell-xps-9350-intel"]);
          default = ["generic-x86_64" "dell-xps-9350-intel"];
          description = "Hardware foundations supported by this home profile.";
        };
        roles = lib.mkOption {
          type = lib.types.listOf (lib.types.enum ["developer" "executive" "it" "sales" "support" "trainer"]);
          default = [];
          description = "Ordered role modules included by the home profile.";
        };
        aspect = lib.mkOption {
          type = lib.types.raw;
          description = "Den aspect resolved into the Home Manager configuration.";
        };
      };
    }
  );
in {
  options.purplefin.profiles = lib.mkOption {
    type = lib.types.attrsOf profileType;
    default = {};
    description = "Typed registry of published Purplefin profile entities.";
  };

  options.purplefin.homeProfiles = lib.mkOption {
    type = lib.types.attrsOf homeProfileType;
    default = {};
    description = "Typed registry of user-scoped Purplefin profiles.";
  };

  config = {
    den.schema.profile.isEntity = true;
  };
}
