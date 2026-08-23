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
      initContent = builtins.readFile ./rootfs/usr/share/finite/zsh/.zshrc;
    };

    programs.fzf = {
      enable = true;
      enableZshIntegration = true;
    };

    xdg.configFile = {
      "ghostty/config".source = ./rootfs/usr/share/finite/ghostty/config.ghostty;
      "zsh/aliases.zsh".source = ./rootfs/usr/share/finite/zsh/aliases.zsh;
      "zsh/bindings.zsh".source = ./rootfs/usr/share/finite/zsh/bindings.zsh;
      "zsh/fzf.zsh".source = ./rootfs/usr/share/finite/zsh/fzf.zsh;
      "zsh/prompt.zsh".source = ./rootfs/usr/share/finite/zsh/prompt.zsh;
      "zsh/starship.toml".source = ./rootfs/usr/share/finite/zsh/starship.toml;
    };
  };
}
