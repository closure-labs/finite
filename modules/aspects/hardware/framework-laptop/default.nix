_: {
  den.aspects.features.hardware.framework-laptop.bootc.finite = {
    hardware = "framework-laptop";
    build = {
      steps = [
        {
          name = "hardware-framework-laptop";
          order = 900;
          script = ./apply.sh;
        }
      ];
      sourcePaths = [./apply.sh];
    };
  };
}
