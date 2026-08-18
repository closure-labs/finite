_: {
  den.aspects.features.roles.executive.bootc = {lib, ...}: {
    purplefin = {
      roles = lib.mkAfter ["executive"];
      build = {
        steps = lib.mkAfter [
          {
            name = "executive";
            order = 350;
            script = ./apply.sh;
          }
        ];
        sourcePaths = [
          ./apply.sh
          ./rootfs
        ];
      };
    };
  };
}
