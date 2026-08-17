{den, ...}: {
  den.aspects.features.roles.developer = {
    includes = [den.aspects.features.capabilities.devops];
    bootc = {lib, ...}: {
      purplefin = {
        roles = lib.mkAfter ["developer"];
        build = {
          steps = lib.mkAfter [
            {
              name = "developer";
              order = 310;
              script = ./apply.sh;
            }
          ];
          sourcePaths = [./apply.sh];
        };
      };
    };
  };
}
