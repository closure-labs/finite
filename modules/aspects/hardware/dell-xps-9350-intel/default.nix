_: {
  den.aspects.features.hardware.dell-xps-9350-intel.bootc.purplefin = {
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
}
