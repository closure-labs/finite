_: {
  den.aspects.features.capabilities.devops.homeManager = {
    config,
    pkgs,
    ...
  }: {
    home.packages = with pkgs; [
      (config.lib.nixGL.wrap ghostty)
      ansible
      openbao
      opentofu
      packer
    ];

    programs.zsh = {
      enable = true;
      autosuggestion.enable = true;
      enableCompletion = true;
      historySubstringSearch.enable = true;
      syntaxHighlighting.enable = true;
      initContent = builtins.readFile ./rootfs/usr/share/purplefin/zsh/.zshrc;
    };

    programs.fzf = {
      enable = true;
      enableZshIntegration = true;
    };

    xdg.configFile = {
      "ghostty/config".source = ./rootfs/usr/share/purplefin/ghostty/config.ghostty;
      "zsh/aliases.zsh".source = ./rootfs/usr/share/purplefin/zsh/aliases.zsh;
      "zsh/bindings.zsh".source = ./rootfs/usr/share/purplefin/zsh/bindings.zsh;
      "zsh/fzf.zsh".source = ./rootfs/usr/share/purplefin/zsh/fzf.zsh;
      "zsh/prompt.zsh".source = ./rootfs/usr/share/purplefin/zsh/prompt.zsh;
      "zsh/starship.toml".source = ./rootfs/usr/share/purplefin/zsh/starship.toml;
    };
  };
}
