{den, ...}: {
  den.aspects.features.roles.support = {
    includes = [den.aspects.features.capabilities.devops];
    homeManager = {
      config,
      pkgs,
      ...
    }: let
      espanso = config.lib.nixGL.wrap pkgs.espanso;
    in {
      home = {
        packages = [espanso];
        sessionVariables.PURPLEFIN_ROLE_SUPPORT = "1";
      };
      services.flatpak.packages = ["io.github.totoshko88.RustConn"];
      systemd.user.services.espanso = {
        Unit = {
          Description = "Espanso text expander";
          After = ["graphical-session.target"];
          PartOf = ["graphical-session.target"];
        };
        Service = {
          ExecStart = "${espanso}/bin/espanso launcher";
          Restart = "on-failure";
          RestartSec = 3;
        };
        Install.WantedBy = ["graphical-session.target"];
      };
    };
  };
}
