{
  config,
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
    dotDir = "${config.xdg.configHome}/zsh";
    envExtra = builtins.readFile (finiteHomeAssets.devops + "/zsh/.zshenv");
    autosuggestion.enable = true;
    enableCompletion = true;
    completionInit = ''
      mkdir -p "${config.xdg.cacheHome}/zsh"
      autoload -Uz compinit
      compinit -d "${config.xdg.cacheHome}/zsh/zcompdump"
    '';
    history = {
      path = "${config.xdg.stateHome}/zsh/history";
      size = 100000;
      save = 100000;
      append = true;
      expireDuplicatesFirst = true;
      findNoDups = true;
    };
    historySubstringSearch.enable = true;
    plugins = [
      {
        name = "zsh-vi-mode";
        file = "share/zsh-vi-mode/zsh-vi-mode.plugin.zsh";
        src = pkgs.zsh-vi-mode;
      }
    ];
    syntaxHighlighting.enable = true;
    # The common base sets Brew precedence. Home Manager owns Zsh integrations.
    initContent = builtins.readFile (finiteHomeAssets.devops + "/zsh/.zshrc");
  };

  programs.fzf = {
    enable = true;
    enableZshIntegration = true;
  };

  xdg.configFile = {
    "ghostty/config.ghostty".text =
      builtins.replaceStrings
      ["command = /usr/bin/zsh"]
      ["command = ${config.programs.zsh.package}/bin/zsh"]
      (builtins.readFile (finiteHomeAssets.devops + "/ghostty/config.ghostty"));
    "zsh/aliases.zsh".source = finiteHomeAssets.devops + "/zsh/aliases.zsh";
    "zsh/bindings.zsh".source = finiteHomeAssets.devops + "/zsh/bindings.zsh";
    "zsh/fzf.zsh".source = finiteHomeAssets.devops + "/zsh/fzf.zsh";
    "zsh/prompt.zsh".source = finiteHomeAssets.devops + "/zsh/prompt.zsh";
    "zsh/starship.toml".source = finiteHomeAssets.devops + "/zsh/starship.toml";
  };
}
