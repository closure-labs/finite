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
        description = "Mutable upstream channel used only by the source updater.";
      };
      architecture = lib.mkOption {
        type = lib.types.enum ["amd64"];
        description = "OCI architecture selected by the locked upstream source.";
      };
      digest = lib.mkOption {
        type = lib.types.strMatching "sha256:[0-9a-f]{64}";
        description = "Immutable upstream OCI digest committed by npins.";
      };
      archiveHash = lib.mkOption {
        type = lib.types.strMatching "sha256-[A-Za-z0-9+/]{43}=";
        description = "Nix fixed-output hash for the upstream OCI archive.";
      };
      cosignIdentity = lib.mkOption {
        type = lib.types.str;
        description = "Required keyless signing identity for the upstream digest.";
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
          "dell-xps-9350-intel"
          "framework-laptop"
          "generic-x86_64"
        ]
      );
      default = null;
      description = "Exactly one hardware target for the composed image.";
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

    build = {
      steps = lib.mkOption {
        type = lib.types.listOf (
          lib.types.submodule {
            options = {
              name = lib.mkOption {
                type = lib.types.strMatching "[a-z0-9._-]+";
                description = "Stable build-step identifier recorded in image metadata.";
              };
              order = lib.mkOption {
                type = lib.types.int;
                description = "Deterministic ordering key for the profile build.";
              };
              script = lib.mkOption {
                type = lib.types.path;
                description = "Aspect-owned executable build step.";
              };
            };
          }
        );
        default = [];
        description = "Build steps contributed by the resolved Den aspect graph.";
      };

      sourcePaths = lib.mkOption {
        type = lib.types.listOf lib.types.path;
        default = [];
        description = "Aspect-owned source closure that affects the image build input.";
      };
    };
  };
}
