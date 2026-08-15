{lib, ...}: {
  options.purplefin = {
    profileName = lib.mkOption {
      type = lib.types.strMatching "[a-z0-9._-]+";
      description = "Stable name used by the bootc build and published image metadata.";
    };

    parent = lib.mkOption {
      type = lib.types.nullOr (lib.types.strMatching "[a-z0-9._-]+");
      default = null;
      description = "Optional staged base profile inherited by this profile.";
    };

    base.enable = lib.mkEnableOption "the shared Purplefin base module";

    upstream = {
      image = lib.mkOption {
        type = lib.types.str;
        description = "OCI repository used as the complete Purplefin base.";
      };
      tag = lib.mkOption {
        type = lib.types.strMatching "[a-z0-9._-]+";
        description = "Verified upstream channel resolved to a digest by CI.";
      };
      preserve = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Require the upstream filesystem and policy to remain intact except for additive Purplefin modules.";
      };
    };

    roles = lib.mkOption {
      type = lib.types.listOf (
        lib.types.enum [
          "developer"
          "executive"
          "it"
          "sales"
          "support"
          "trainer"
        ]
      );
      default = [];
      description = "Ordered role modules applied between base and hardware.";
    };

    hardware = lib.mkOption {
      type = lib.types.nullOr (
        lib.types.enum [
          "hardware-dell-xps-9350-intel"
          "hardware-framework-laptop"
          "hardware-generic-x86_64"
        ]
      );
      default = null;
      description = "Exactly one Fedora hardware module for the composed image.";
    };

    tags = lib.mkOption {
      type = lib.types.listOf (lib.types.strMatching "[a-z0-9._-]+");
      default = [];
      description = "Ordered registry tags; the first tag is canonical.";
    };

    imageBuilder = {
      rootFilesystem = lib.mkOption {
        type = lib.types.enum [
          "btrfs"
          "ext4"
          "xfs"
        ];
        default = "ext4";
        description = "Default filesystem passed to image-builder for bootc artifacts.";
      };

      filesystems = lib.mkOption {
        type = lib.types.listOf (
          lib.types.submodule {
            options = {
              mountpoint = lib.mkOption {
                type = lib.types.enum [
                  "/"
                  "/boot"
                ];
              };
              minsize = lib.mkOption {
                type = lib.types.ints.positive;
                description = "Minimum filesystem size in bytes.";
              };
            };
          }
        );
        default = [
          {
            mountpoint = "/";
            minsize = 21474836480;
          }
          {
            mountpoint = "/boot";
            minsize = 2147483648;
          }
        ];
        description = "Bootc-supported filesystem Blueprint customizations.";
      };
    };
  };
}
