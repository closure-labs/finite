{
  config,
  finiteHomeAssets,
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
    initContent = builtins.readFile (finiteHomeAssets.devops + "/zsh/.zshrc");
  };

  programs.fzf = {
    enable = true;
    enableZshIntegration = true;
  };

  xdg.configFile = {
    "ghostty/config".source = finiteHomeAssets.devops + "/ghostty/config.ghostty";
    "zsh/aliases.zsh".source = finiteHomeAssets.devops + "/zsh/aliases.zsh";
    "zsh/bindings.zsh".source = finiteHomeAssets.devops + "/zsh/bindings.zsh";
    "zsh/fzf.zsh".source = finiteHomeAssets.devops + "/zsh/fzf.zsh";
    "zsh/prompt.zsh".source = finiteHomeAssets.devops + "/zsh/prompt.zsh";
    "zsh/starship.toml".source = finiteHomeAssets.devops + "/zsh/starship.toml";
  };
}
