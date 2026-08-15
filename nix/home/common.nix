{
  lib,
  profile,
  ...
}: {
  home = {
    username = lib.mkDefault "purplefin";
    homeDirectory = lib.mkDefault "/var/home/purplefin";
    stateVersion = "26.05";
    sessionVariables.PURPLEFIN_PROFILE = profile.profileName;
  };

  programs = {
    home-manager.enable = true;
    git.enable = true;
    zsh.enable = true;
  };

  xdg = {
    enable = true;
    configFile."purplefin/profile.json".text = builtins.toJSON {
      inherit
        (profile)
        hardware
        modules
        parent
        roles
        tags
        ;
    };
  };
}
