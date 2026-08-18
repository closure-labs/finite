_: {
  den.aspects.features.roles.trainer = {
    bootc = {lib, ...}: {
      purplefin = {
        roles = lib.mkAfter ["trainer"];
        build = {
          steps = lib.mkAfter [
            {
              name = "trainer";
              order = 330;
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
    homeManager.home.sessionVariables.PURPLEFIN_ROLE_TRAINER = "1";
  };
}
