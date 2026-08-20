_: {
  den.aspects.features.hardware.dell-xps-9350-intel = {
    bootc.purplefin = {
      hardware = "dell-xps-9350-intel";
      build = {
        steps = [
          {
            name = "hardware-dell-xps-9350-intel";
            order = 900;
            script = ./apply.sh;
          }
        ];
        sourcePaths = [
          ./apply.sh
          ./build
          ./configure.sh
          ./rootfs
        ];
      };
    };

    homeManager = {
      home.sessionVariables.PURPLEFIN_HARDWARE = "dell-xps-9350-intel";
      xdg.configFile."purplefin/dell-xps-9350-panel.conf".source =
        ./rootfs/usr/share/purplefin/dell-xps-9350-panel.conf;

      systemd.user = {
        paths.purplefin-firefox-pipewire-camera = {
          Unit.Description = "Watch Firefox profiles requiring the IPU7 PipeWire camera";
          Path = {
            PathChanged = "%h/.var/app/org.mozilla.firefox/config/mozilla/firefox/profiles.ini";
            Unit = "purplefin-firefox-pipewire-camera.service";
          };
          Install.WantedBy = ["default.target"];
        };
        services = {
          purplefin-firefox-pipewire-camera = {
            Unit = {
              Description = "Configure Firefox to use the IPU7 PipeWire camera";
              ConditionPathExists = "%h/.var/app/org.mozilla.firefox/config/mozilla/firefox/profiles.ini";
            };
            Service = {
              Type = "oneshot";
              ExecStart = "/usr/libexec/purplefin/configure-firefox-pipewire-camera";
            };
          };
          purplefin-dell-xps-9350-panel = {
            Unit = {
              Description = "Apply Dell XPS 13 9350 AC/battery panel policy";
              After = ["graphical-session-pre.target"];
              PartOf = ["graphical-session.target"];
              ConditionPathExists = "/sys/class/dmi/id/product_name";
            };
            Service = {
              ExecStart = "/usr/libexec/purplefin/dell-xps-9350-panel-policy --watch";
              Restart = "on-failure";
              RestartSec = 10;
            };
            Install.WantedBy = ["graphical-session.target"];
          };
        };
      };
    };
  };
}
