{
  lib,
  pkgs,
  ...
}: let
  panelPolicy = pkgs.writeShellApplication {
    name = "finite-dell-xps-9350-panel-policy";
    runtimeInputs = with pkgs; [coreutils gawk glib gnugrep];
    text = builtins.readFile ./dell-xps-9350-panel-policy;
  };
in {
  home.sessionVariables.FINITE_HARDWARE = "dell-xps-9350-intel";
  xdg.configFile."finite/dell-xps-9350-panel.conf".source =
    ./rootfs/usr/share/finite/dell-xps-9350-panel.conf;
  home.packages = [panelPolicy];

  systemd.user.services.finite-dell-xps-9350-panel = {
    Unit = {
      Description = "Apply Dell XPS 13 9350 AC/battery panel policy";
      After = ["graphical-session-pre.target"];
      PartOf = ["graphical-session.target"];
      ConditionPathExists = "/sys/class/dmi/id/product_name";
    };
    Service = {
      ExecStart = "${lib.getExe panelPolicy} --watch";
      Restart = "on-failure";
      RestartSec = 10;
    };
    Install.WantedBy = ["graphical-session.target"];
  };
}
