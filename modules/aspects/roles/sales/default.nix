_: {
  den.aspects.features.roles.sales = {
    bootc = {lib, ...}: {
      purplefin = {
        roles = lib.mkAfter ["sales"];
        build = {
          steps = lib.mkAfter [
            {
              name = "sales";
              order = 320;
              script = ./apply.sh;
            }
          ];
          sourcePaths = [
            ./apply.sh
            ./manifests
          ];
        };
      };
    };
    homeManager.home.sessionVariables.PURPLEFIN_ROLE_SALES = "1";
  };
}
