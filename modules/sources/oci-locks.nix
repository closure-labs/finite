{lib, ...}: let
  bluefinLock = builtins.fromJSON (builtins.readFile ../../sources/bluefin.json);
  imageBuilderLock = builtins.fromJSON (builtins.readFile ../../sources/image-builder.json);
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
        type = lib.types.enum ["amd64"];
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
  options.purplefin.sources = {
    bluefin = lib.mkOption {
      type = ociSourceType;
      readOnly = true;
      description = "Typed, signed Bluefin OCI lock.";
    };
    imageBuilder = lib.mkOption {
      type = ociSourceType;
      readOnly = true;
      description = "Typed OSBuild Image Builder OCI lock.";
    };
  };

  config = assert bluefinLock.cosign != null; {
    purplefin.sources = {
      bluefin = bluefinLock;
      imageBuilder = imageBuilderLock // {cosign = null;};
    };

    den.aspects.sources = {
      bluefin = {};
      image-builder = {};
    };
  };
}
