{
  config,
  inputs,
  pkgs,
  ...
}: {
  home = {
    packages =
      [inputs.devenv.packages.${pkgs.stdenv.hostPlatform.system}.devenv]
      ++ (with pkgs; [rustup cargo-audit cargo-edit cargo-watch])
      ++ [(config.lib.nixGL.wrap pkgs.vscodium)];
    sessionVariables.FINITE_ROLE_DEVELOPER = "1";
  };
}
