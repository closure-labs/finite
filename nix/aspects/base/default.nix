{
  bootc = {
    purplefin.base.enable = true;
    purplefin.upstream = {
      image = "ghcr.io/projectbluefin/bluefin";
      tag = "stable";
      preserve = true;
    };
  };
  homeManager = ./home.nix;
}
