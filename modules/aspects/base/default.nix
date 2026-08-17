{...}: {
  den.aspects.features.base = {
    bootc = {
      purplefin = {
        base.enable = true;
        upstream = {
          image = "ghcr.io/projectbluefin/bluefin";
          tag = "stable";
          preserve = true;
        };
        build = {
          steps = [
            {
              name = "base";
              order = 100;
              script = ./apply.sh;
            }
          ];
          sourcePaths = [
            ./apply.sh
            ./independently-managed-rpms.list
            ./manifests
            ./packages-bitwarden-cli
            ./rootfs
          ];
        };
      };
    };
    homeManager = ../../../home/base.nix;
  };
}
