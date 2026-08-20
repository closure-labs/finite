{den, ...}: {
  den.aspects.features.roles.developer = {
    includes = [den.aspects.features.capabilities.devops];
    homeManager = {pkgs, ...}: {
      home.packages = with pkgs; [rustup cargo-audit cargo-edit cargo-watch];
      home.sessionVariables.PURPLEFIN_ROLE_DEVELOPER = "1";
    };
  };
}
