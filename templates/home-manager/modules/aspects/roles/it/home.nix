{pkgs, ...}: {
  home = {
    packages = [pkgs.rustdesk-flutter];
    sessionVariables.FINITE_ROLE_IT = "1";
  };
}
