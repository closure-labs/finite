_: {
  den.aspects.features.roles.trainer.homeManager = {
    home.sessionVariables.PURPLEFIN_ROLE_TRAINER = "1";
    xdg.desktopEntries.purplefin-grist = {
      name = "Grist";
      comment = "Open Vates Grist in Firefox";
      exec = "firefox --new-window https://grist.vates.tech";
      icon = "firefox";
      categories = ["Office" "WebBrowser"];
    };
  };
}
