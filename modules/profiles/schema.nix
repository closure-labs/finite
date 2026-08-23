{
  config,
  den,
  lib,
  ...
}: let
  profileType = lib.types.submodule (
    {name, ...}: {
      options = {
        name = lib.mkOption {
          type = lib.types.strMatching "[a-z0-9._-]+";
          default = name;
          description = "Published Finite profile identifier.";
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
  foundationType = lib.types.submodule (
    {name, ...}: {
      options = {
        name = lib.mkOption {
          type = lib.types.enum ["bluefin" "bluefin-dx"];
          default = name;
          description = "Finite foundation identifier.";
        };
        template = lib.mkOption {
          type = lib.types.enum ["home-bluefin" "home-bluefin-dx"];
          description = "Native standalone Home Manager template.";
        };
        profiles = lib.mkOption {
          type = lib.types.attrsOf (lib.types.strMatching "[a-z0-9._-]+");
          description = "Bootc profile selected for each supported hardware target.";
        };
      };
    }
  );
  hardwareType = lib.types.submodule (
    {name, ...}: {
      options = {
        name = lib.mkOption {
          type = lib.types.enum ["generic-x86_64" "dell-xps-9350-intel"];
          default = name;
          description = "Finite hardware aspect identifier.";
        };
        label = lib.mkOption {
          type = lib.types.str;
          description = "Human-readable hardware label.";
        };
        aspect = lib.mkOption {
          type = lib.types.raw;
          description = "Den hardware aspect used by standalone homes.";
        };
      };
    }
  );
  roleType = lib.types.submodule (
    {name, ...}: {
      options = {
        name = lib.mkOption {
          type = lib.types.enum ["developer" "executive" "it" "sales" "support" "trainer"];
          default = name;
          description = "Finite role aspect identifier.";
        };
        label = lib.mkOption {
          type = lib.types.str;
          description = "Human-readable checklist label.";
        };
        order = lib.mkOption {
          type = lib.types.ints.unsigned;
          description = "Canonical role ordering key.";
        };
        aspect = lib.mkOption {
          type = lib.types.raw;
          description = "Den role aspect used by standalone homes.";
        };
      };
    }
  );
in {
  options.finite = {
    profiles = lib.mkOption {
      type = lib.types.attrsOf profileType;
      default = {};
      description = "Typed registry of published Finite bootc profile entities.";
    };
    home = {
      foundations = lib.mkOption {
        type = lib.types.attrsOf foundationType;
        default = {};
        description = "Typed Home Manager foundation catalog.";
      };
      hardware = lib.mkOption {
        type = lib.types.attrsOf hardwareType;
        default = {};
        description = "Typed Home Manager hardware catalog.";
      };
      roles = lib.mkOption {
        type = lib.types.attrsOf roleType;
        default = {};
        description = "Typed composable Home Manager role catalog.";
      };
    };
  };

  config.den.hosts.x86_64-linux =
    lib.mapAttrs (
      name: profile: {
        class = "bootc";
        hostName = name;
        inherit (profile) aspect;
        excludes = [den.default];
        intoAttr = [];
        instantiate = {modules, ...}:
          lib.evalModules {
            modules = [./bootc-class.nix] ++ modules;
          };
      }
    )
    config.finite.profiles;
}
