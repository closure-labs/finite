{lib, ...}: let
  lock = builtins.fromJSON (builtins.readFile ../npins/sources.json);
  pin = lock.pins."bluefin-stable";
in {
  options.purplefin.sources.bluefin = lib.mkOption {
    type = lib.types.submodule {
      options = {
        image = lib.mkOption {
          type = lib.types.str;
          description = "OCI repository discovered and locked by npins.";
        };
        tag = lib.mkOption {
          type = lib.types.strMatching "[a-z0-9._-]+";
          description = "Mutable upstream channel used only for npins discovery.";
        };
        architecture = lib.mkOption {
          type = lib.types.enum ["amd64"];
          description = "OCI architecture selected by the container pin.";
        };
        digest = lib.mkOption {
          type = lib.types.strMatching "sha256:[0-9a-f]{64}";
          description = "Immutable OCI manifest digest used by every image build.";
        };
        archiveHash = lib.mkOption {
          type = lib.types.strMatching "sha256-[A-Za-z0-9+/]{43}=";
          description = "Nix fixed-output hash for the npins OCI archive.";
        };
        cosignIdentity = lib.mkOption {
          type = lib.types.str;
          description = "Required keyless signing identity for the locked image.";
        };
      };
    };
    readOnly = true;
    description = "Typed Bluefin source derived from the npins container lock.";
  };

  config = {
    purplefin.sources.bluefin = {
      image = pin.image_name;
      tag = pin.image_tag;
      architecture = pin.arch;
      digest = pin.image_digest;
      archiveHash = pin.hash;
      cosignIdentity = "https://github.com/projectbluefin/actions/.github/workflows/reusable-build.yml@refs/tags/v1";
    };

    den.aspects.sources.bluefin = {};
  };
}
