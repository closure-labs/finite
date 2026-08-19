_: {
  den.aspects.features.roles.it.homeManager = {
    config,
    pkgs,
    ...
  }: {
    home = {
      packages = [(config.lib.nixGL.wrap pkgs.rustdesk-flutter)];
      sessionVariables.PURPLEFIN_ROLE_IT = "1";
    };
  };
}
