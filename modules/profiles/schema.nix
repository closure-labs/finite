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
in {
  options.purplefin.profiles = lib.mkOption {
    type = lib.types.attrsOf profileType;
    default = {};
    description = "Typed registry of published Purplefin profile entities.";
  };

  config = {
    den.schema.profile.isEntity = true;
  };
}
