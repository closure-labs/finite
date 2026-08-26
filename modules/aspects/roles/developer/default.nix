{den, ...}: {
  den.aspects.features.roles.developer = {
    includes = [den.aspects.features.capabilities.devops];
    homeManager = {
      finiteHomeDependencies,
      pkgs,
      ...
    }: {
      home.packages =
        [finiteHomeDependencies.devenvPackage]
        ++ (with pkgs; [rustup cargo-audit cargo-edit cargo-watch]);
      home.sessionVariables.FINITE_ROLE_DEVELOPER = "1";
    };
  };
}
