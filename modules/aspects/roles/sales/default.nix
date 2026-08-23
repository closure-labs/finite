_: {
  den.aspects.features.roles.sales.homeManager = {
    config,
    pkgs,
    ...
  }: {
    home = {
      packages = [(config.lib.nixGL.wrap pkgs.thunderbird)];
      sessionVariables.FINITE_ROLE_SALES = "1";
    };
  };
}
