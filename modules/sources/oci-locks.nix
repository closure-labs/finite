{
  lib,
  project,
  ...
}: let
  bluefinLock = builtins.fromJSON (builtins.readFile ../../sources/bluefin.json);
  bluefinDxLock = builtins.fromJSON (builtins.readFile ../../sources/bluefin-dx.json);
  determinateNixLock = builtins.fromJSON (builtins.readFile ../../sources/determinate-nix.json);
  ociSourceType = lib.types.submodule {
    options = {
      schema = lib.mkOption {
        type = lib.types.enum [1];
        description = "OCI lock schema version.";
      };
      image = lib.mkOption {
        type = lib.types.strMatching "[a-z0-9._/-]+";
        description = "OCI repository resolved by the source updater.";
      };
      tag = lib.mkOption {
        type = lib.types.strMatching "[A-Za-z0-9._-]+";
        description = "Mutable discovery tag; never used as the immutable build boundary.";
      };
      architecture = lib.mkOption {
        type = lib.types.enum [project.platform.ociArchitecture];
        description = "OCI architecture selected while resolving the manifest.";
      };
      digest = lib.mkOption {
        type = lib.types.strMatching "sha256:[0-9a-f]{64}";
        description = "Immutable architecture-selected OCI manifest digest.";
      };
      cosign = lib.mkOption {
        type = lib.types.nullOr (lib.types.submodule {
          options = {
            issuer = lib.mkOption {type = lib.types.str;};
            identity = lib.mkOption {type = lib.types.str;};
          };
        });
        default = null;
        description = "Optional required keyless signature identity.";
      };
    };
  };
in {
  options.finite.sources = {
    determinateNix = lib.mkOption {
      type = lib.types.submodule {
        options = {
          schema = lib.mkOption {type = lib.types.enum [1];};
          version = lib.mkOption {type = lib.types.strMatching "[0-9]+\\.[0-9]+\\.[0-9]+";};
          minimumRuntimeVersion = lib.mkOption {
            type = lib.types.strMatching "[0-9]+\\.[0-9]+\\.[0-9]+";
            description = "Oldest Determinate Nix runtime accepted in a published image seed.";
          };
          architecture = lib.mkOption {type = lib.types.enum [project.platform.system];};
          installer = lib.mkOption {
            type = lib.types.submodule {
              options = {
                url = lib.mkOption {type = lib.types.strMatching "https://.*";};
                sha256 = lib.mkOption {type = lib.types.strMatching "[0-9a-f]{64}";};
              };
            };
          };
          selinuxPolicy = lib.mkOption {
            type = lib.types.submodule {
              options = {
                url = lib.mkOption {type = lib.types.strMatching "https://.*";};
                sha256 = lib.mkOption {type = lib.types.strMatching "[0-9a-f]{64}";};
              };
            };
          };
          selinuxFileContexts = lib.mkOption {
            type = lib.types.submodule {
              options = {
                url = lib.mkOption {type = lib.types.strMatching "https://.*";};
                sha256 = lib.mkOption {type = lib.types.strMatching "[0-9a-f]{64}";};
              };
            };
          };
        };
      };
      readOnly = true;
      description = "Pinned Determinate Nix bootstrap and SELinux policy.";
    };

    bluefin = lib.mkOption {
      type = ociSourceType;
      readOnly = true;
      description = "Typed, signed Bluefin OCI lock.";
    };
    bluefinDx = lib.mkOption {
      type = ociSourceType;
      readOnly = true;
      description = "Typed, signed Bluefin DX OCI lock.";
    };
  };

  config = assert bluefinLock.cosign != null && bluefinDxLock.cosign != null; {
    finite.sources = {
      determinateNix = determinateNixLock;
      bluefin = bluefinLock;
      bluefinDx = bluefinDxLock;
    };

    den.aspects.sources = {
      determinate-nix = {};
      bluefin = {};
      bluefin-dx = {};
    };
  };
}
