{
  config,
  den,
  ...
}: {
  den.aspects.features.base = {
    includes = [den.aspects.sources.bluefin];
    bootc = {
      purplefin = {
        base.enable = true;
        upstream = config.purplefin.sources.bluefin // {preserve = true;};
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
