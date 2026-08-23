{den, ...}: {
  den.aspects.features.roles.developer = {
    includes = [den.aspects.features.capabilities.devops];
    homeManager = {
      inputs,
      pkgs,
      ...
    }: {
      home.packages =
        [inputs.devenv.packages.${pkgs.stdenv.hostPlatform.system}.devenv]
        ++ (with pkgs; [rustup cargo-audit cargo-edit cargo-watch]);
      home.sessionVariables.FINITE_ROLE_DEVELOPER = "1";
    };
  };
}
