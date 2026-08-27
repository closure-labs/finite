_: {
  den.aspects.features.hardware.next-x86_64.bootc.finite = {
    hardware = "next-x86_64";
    build = {
      steps = [
        {
          name = "hardware-next-x86_64";
          order = 900;
          script = ./apply.sh;
        }
      ];
      sourcePaths = [
        ./apply.sh
        ../../../../sources/kernel-next.json
      ];
    };
  };
}
