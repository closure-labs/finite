{
  config,
  inputs,
  lib,
  pkgs,
  ...
}: let
  system = pkgs.stdenv.hostPlatform.system;
in {
  imports = [
    inputs.determinate.homeManagerModules.default
    inputs.nix-flatpak.homeManagerModules.nix-flatpak
  ];

  home = {
    username = lib.mkDefault "finite";
    homeDirectory = lib.mkDefault "/var/home/finite";
    stateVersion = "26.05";
    packages = with pkgs; [
      atuin
      bash-preexec
      bat
      bitwarden-cli
      (config.lib.nixGL.wrap inputs.nixpkgs-weekly.legacyPackages.${system}.bitwarden-desktop)
      chezmoi
      codex
      direnv
      dysk
      eza
      fd
      fzf
      gh
      marp-cli
      mise
      neovim
      podman-tui
      ripgrep
      starship
      tealdeer
      trash-cli
      ugrep
      uutils-coreutils-noprefix
      yq-go
      zoxide
      zsh-autosuggestions
      zsh-fast-syntax-highlighting
      zsh-history-substring-search
      zsh-vi-mode
    ];
  };

  nix.package = null;

  targets.genericLinux = {
    enable = true;
    nixGL = {
      packages = inputs.nixgl.packages.${system};
      # Home Manager's current "mesa" wrapper is the NixGL Intel/Mesa auto
      # profile and works with Intel, AMD, and Nouveau host drivers.
      defaultWrapper = "mesa";
      installScripts = ["mesa"];
    };
  };

  services.flatpak = {
    enable = true;
    uninstallUnmanaged = false;
    update.auto.enable = false;
    packages = [
      "app.drey.Damask"
      "be.alexandervanhee.gradia"
      "com.github.PintaProject.Pinta"
      "com.github.tchx84.Flatseal"
      "com.mattjakeman.ExtensionManager"
      "com.nextcloud.desktopclient.nextcloud"
      "com.ranfdev.DistroShelf"
      "com.spotify.Client"
      "hu.irl.cameractrls"
      "im.riot.Riot"
      "io.github.flattool.Ignition"
      "io.github.flattool.Warehouse"
      "io.github.pleromix.IceBox"
      "io.github.zaedus.spider"
      "io.gitlab.adhami3310.Impression"
      "io.missioncenter.MissionCenter"
      "it.mijorus.gearlever"
      "it.mijorus.smile"
      "net.cozic.joplin_desktop"
      "org.chromium.Chromium"
      "org.libreoffice.LibreOffice"
      "org.signal.Signal"
      "page.tesk.Refine"
    ];
  };

  programs = {
    git.enable = true;
    nh.enable = true;
    zsh.enable = true;
  };

  xdg.enable = true;
}
