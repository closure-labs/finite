_: {
  den.aspects.features.hardware.dell-xps-9350-intel = {
    bootc.finite = {
      hardware = "dell-xps-9350-intel";
      build = {
        steps = [
          {
            name = "hardware-dell-xps-9350-intel";
            order = 900;
            script = ./apply.sh;
          }
        ];
        sourcePaths = [
          ./apply.sh
          ./build
          ./configure.sh
          ./rootfs
        ];
      };
    };

    homeManager.imports = [../../../../templates/home-manager/modules/aspects/hardware/dell-xps-9350-intel/home.nix];
  };
}
