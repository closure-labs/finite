{den, ...}: {
  den.aspects.features.base = {
    includes = [
      den.aspects.sources.determinate-nix
    ];
    bootc = {
      finite = {
        base.enable = true;
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
            ./install-nix-systemd-units.sh
            ./rootfs
            ../../../sources/determinate-nix.json
          ];
        };
      };
    };
    homeManager.imports = [../../../templates/home-manager/modules/aspects/base/home.nix];
  };
}
