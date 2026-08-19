{
  config,
  den,
  ...
}: {
  den.aspects.features.base = {
    includes = [
      den.aspects.sources.bluefin
      den.aspects.sources.determinate-nix
    ];
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
            ./install-determinate-nix.sh
            ./independently-managed-rpms.list
            ./manifests
            ./packages-bitwarden-cli
            ./rootfs
            ../../../sources/determinate-nix.json
          ];
        };
      };
    };
    homeManager = {lib, ...}: {
      home = {
        username = lib.mkDefault "purplefin";
        homeDirectory = lib.mkDefault "/var/home/purplefin";
        stateVersion = "26.05";
      };

      programs = {
        home-manager.enable = true;
        git.enable = true;
        zsh.enable = true;
      };

      xdg.enable = true;
    };
  };
}
