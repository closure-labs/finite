{
  catalog,
  lib,
  ...
}: let
  foundationType = lib.types.submodule (
    {name, ...}: {
      options = {
        name = lib.mkOption {
          type = lib.types.enum catalog.foundationNames;
          default = name;
          description = "Finite foundation identifier.";
        };
        template = lib.mkOption {
          type = lib.types.enum catalog.templateNames;
          description = "Native standalone Home Manager template.";
        };
        profiles = lib.mkOption {
          type = lib.types.attrsOf (lib.types.enum catalog.profileOrder);
          description = "Bootc profile selected for each supported hardware target.";
        };
      };
    }
  );
  hardwareType = lib.types.submodule (
    {name, ...}: {
      options = {
        name = lib.mkOption {
          type = lib.types.enum catalog.homeHardwareNames;
          default = name;
          description = "Finite hardware aspect identifier.";
        };
        label = lib.mkOption {
          type = lib.types.str;
          description = "Human-readable hardware label.";
        };
        imageHardware = lib.mkOption {
          type = lib.types.listOf (lib.types.enum catalog.bootcHardwareNames);
          description = "Bootc hardware targets compatible with this Home Manager aspect.";
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
          type = lib.types.enum catalog.roleNames;
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
  packageType = lib.types.submodule (
    {name, ...}: {
      options = {
        name = lib.mkOption {
          type = lib.types.enum catalog.packageNames;
          default = name;
          description = "Finite optional Home Manager package identifier.";
        };
        label = lib.mkOption {
          type = lib.types.str;
          description = "Human-readable package label.";
        };
        description = lib.mkOption {
          type = lib.types.str;
          description = "Short package description shown by finite-configure.";
        };
        order = lib.mkOption {
          type = lib.types.ints.unsigned;
          description = "Canonical package ordering key.";
        };
      };
    }
  );
in {
  options.finite = {
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
      packages = lib.mkOption {
        type = lib.types.attrsOf packageType;
        default = {};
        description = "Typed optional Home Manager package catalog.";
      };
    };
  };
}
