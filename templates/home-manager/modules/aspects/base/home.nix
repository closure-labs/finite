{
  config,
  inputs,
  lib,
  pkgs,
  ...
}: let
  system = pkgs.stdenv.hostPlatform.system;
  weekly = inputs.nixpkgs-weekly.legacyPackages.${system};
in {
  imports = [
    inputs.determinate.homeManagerModules.default
    inputs.nix-flatpak.homeManagerModules.nix-flatpak
  ];

  home = {
    username = lib.mkDefault "finite";
    homeDirectory = lib.mkDefault "/var/home/finite";
    stateVersion = "26.05";
    packages =
      (with pkgs; [
        atuin
        bash-preexec
        bat
        chezmoi
        direnv
        dysk
        eza
        fd
        gh
        marp-cli
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
      ])
      ++ [
        (config.lib.nixGL.wrap weekly.bitwarden-desktop)
        (config.lib.nixGL.wrap weekly.element-desktop)
        (config.lib.nixGL.wrap weekly.firefox)
        (config.lib.nixGL.wrap weekly.libreoffice)
        (config.lib.nixGL.wrap weekly.nextcloud-client)
        (config.lib.nixGL.wrap pkgs.thunderbird)
        (config.lib.nixGL.wrap pkgs.vlc)
        weekly.bbrew
        weekly.bitwarden-cli
        weekly.mise
      ];
  };

  fonts.fontconfig.enable = true;

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
      "com.ranfdev.DistroShelf"
      "hu.irl.cameractrls"
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
      "page.tesk.Refine"
    ];
  };

  programs = {
    fzf.enable = true;
    git.enable = true;
    nh.enable = true;
    zsh.enable = true;
  };

  xdg.enable = true;
}
