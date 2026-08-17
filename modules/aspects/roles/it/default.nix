{...}: {
  den.aspects.features.roles.it.bootc = {lib, ...}: {
    purplefin = {
      roles = lib.mkAfter ["it"];
      build = {
        steps = lib.mkAfter [
          {
            name = "it";
            order = 360;
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
}
