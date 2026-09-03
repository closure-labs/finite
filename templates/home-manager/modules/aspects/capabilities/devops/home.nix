{
  finiteHomeAssets,
  pkgs,
  ...
}: let
  ghostty = pkgs.symlinkJoin {
    name = "finite-ghostty-${pkgs.ghostty.version}";
    paths = [pkgs.ghostty];
    postBuild = ''
      desktop="$out/share/applications/com.mitchellh.ghostty.desktop"
      desktop_source=$(readlink -f "$desktop")
      install -m 0444 "$desktop_source" "$desktop.new"
      substituteInPlace "$desktop.new" \
        --replace-fail 'DBusActivatable=true' 'DBusActivatable=false'
      mv -f "$desktop.new" "$desktop"
    '';
    meta.mainProgram = "ghostty";
  };
in {
  home.packages = with pkgs; [
    ghostty
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
    plugins = [
      {
        name = "zsh-vi-mode";
        file = "share/zsh-vi-mode/zsh-vi-mode.plugin.zsh";
        src = pkgs.zsh-vi-mode;
      }
    ];
    syntaxHighlighting.enable = true;
    initContent = builtins.readFile (finiteHomeAssets.devops + "/zsh/.zshrc");
  };

  programs.fzf = {
    enable = true;
    enableZshIntegration = true;
  };

  xdg.configFile = {
    "ghostty/config.ghostty".source = finiteHomeAssets.devops + "/ghostty/config.ghostty";
    "zsh/aliases.zsh".source = finiteHomeAssets.devops + "/zsh/aliases.zsh";
    "zsh/bindings.zsh".source = finiteHomeAssets.devops + "/zsh/bindings.zsh";
    "zsh/fzf.zsh".source = finiteHomeAssets.devops + "/zsh/fzf.zsh";
    "zsh/prompt.zsh".source = finiteHomeAssets.devops + "/zsh/prompt.zsh";
    "zsh/starship.toml".source = finiteHomeAssets.devops + "/zsh/starship.toml";
  };
}
