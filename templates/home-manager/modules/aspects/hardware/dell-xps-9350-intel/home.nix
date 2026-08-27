{finiteHomeAssets, ...}: {
  home.sessionVariables.FINITE_HARDWARE = "dell-xps-9350-intel";
  xdg.configFile."finite/dell-xps-9350-panel.conf".source =
    finiteHomeAssets.dell + "/dell-xps-9350-panel.conf";

  systemd.user = {
    paths.finite-firefox-pipewire-camera = {
      Unit.Description = "Watch Firefox profiles requiring the IPU7 PipeWire camera";
      Path = {
        PathChanged = "%h/.var/app/org.mozilla.firefox/config/mozilla/firefox/profiles.ini";
        Unit = "finite-firefox-pipewire-camera.service";
      };
      Install.WantedBy = ["default.target"];
    };
    services = {
      finite-firefox-pipewire-camera = {
        Unit = {
          Description = "Configure Firefox to use the IPU7 PipeWire camera";
          ConditionPathExists = "%h/.var/app/org.mozilla.firefox/config/mozilla/firefox/profiles.ini";
          ConditionPathIsExecutable = "/usr/libexec/finite/configure-firefox-pipewire-camera";
        };
        Service = {
          Type = "oneshot";
          ExecStart = "/usr/libexec/finite/configure-firefox-pipewire-camera";
        };
      };
      finite-dell-xps-9350-panel = {
        Unit = {
          Description = "Apply Dell XPS 13 9350 AC/battery panel policy";
          After = ["graphical-session-pre.target"];
          PartOf = ["graphical-session.target"];
          ConditionPathExists = "/sys/class/dmi/id/product_name";
          ConditionPathIsExecutable = "/usr/libexec/finite/dell-xps-9350-panel-policy";
        };
        Service = {
          ExecStart = "/usr/libexec/finite/dell-xps-9350-panel-policy --watch";
          Restart = "on-failure";
          RestartSec = 10;
        };
        Install.WantedBy = ["graphical-session.target"];
      };
    };
  };
}
