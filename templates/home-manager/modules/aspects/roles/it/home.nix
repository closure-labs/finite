{
  config,
  pkgs,
  ...
}: {
  home = {
    packages = [(config.lib.nixGL.wrap pkgs.rustdesk-flutter)];
    sessionVariables.FINITE_ROLE_IT = "1";
  };
}
