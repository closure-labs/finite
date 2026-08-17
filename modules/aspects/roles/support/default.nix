{den, ...}: {
  den.aspects.features.roles.support = {
    includes = [den.aspects.features.capabilities.devops];
    bootc = {lib, ...}: {
      purplefin = {
        roles = lib.mkAfter ["support"];
        build = {
          steps = lib.mkAfter [
            {
              name = "support";
              order = 340;
              script = ./apply.sh;
            }
          ];
          sourcePaths = [
            ./apply.sh
            ./manifests
            ./rootfs
          ];
        };
      };
    };
    homeManager.home.sessionVariables.PURPLEFIN_ROLE_SUPPORT = "1";
  };
}
