_: {
  den.aspects.features.hardware.generic-x86_64.bootc.purplefin = {
    hardware = "generic-x86_64";
    build = {
      steps = [
        {
          name = "hardware-generic-x86_64";
          order = 900;
          script = ./apply.sh;
        }
      ];
      sourcePaths = [./apply.sh];
    };
  };
}
