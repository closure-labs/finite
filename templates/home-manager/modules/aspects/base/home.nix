{
  config,
  inputs,
  lib,
  pkgs,
  ...
}: let
  system = pkgs.stdenv.hostPlatform.system;
  weekly = inputs.nixpkgs-weekly.legacyPackages.${system};
  pipewireCameraPolicies =
    # Upstream Firefox keeps the PipeWire camera backend disabled because it
    # replaces V4L2 without a reliable fallback. Restrict it to the Dell IPU7
    # hardware, whose usable libcamera source is exposed through PipeWire.
    lib.optionalAttrs
    ((config.home.sessionVariables.FINITE_HARDWARE or "") == "dell-xps-9350-intel")
    {
      Preferences."media.webrtc.camera.allow-pipewire" = {
        Value = true;
        Status = "locked";
      };
    };
  finiteFirefox = weekly.firefox.override {
    extraPolicies = pipewireCameraPolicies;
  };
  brewPolicy = builtins.fromJSON (builtins.readFile ./brew-packages.json);
  brewFile = pkgs.writeText "finite.Brewfile" (
    lib.concatMapStrings (tap: "tap ${builtins.toJSON tap}\n") brewPolicy.taps
    + lib.concatMapStrings (package: "brew ${builtins.toJSON package.formula}\n") brewPolicy.packages
  );
  brewMigrationStatus = pkgs.writeShellApplication {
    name = "finite-brew-migration-status";
    # Absolute helper paths keep the caller's PATH intact for provider checks.
    runtimeEnv = {
      FINITE_BREW_JQ = "${pkgs.jq}/bin/jq";
      FINITE_BREW_READLINK = "${pkgs.coreutils}/bin/readlink";
    };
    text = builtins.readFile ../../finite-brew-migration-status;
  };
in {
  imports = [
    inputs.determinate.homeManagerModules.default
    inputs.nix-flatpak.homeManagerModules.nix-flatpak
  ];

  home = {
    username = lib.mkDefault "finite";
    homeDirectory = lib.mkDefault "/var/home/finite";
    stateVersion = "26.05";
    # Bluefin's shared CLI tools come from Homebrew; keep Nix-only user apps
    # and the pinned dependencies of Finite's own scripts in Nix.
    packages =
      (with pkgs; [
        marp-cli
        neovim
      ])
      ++ [
        brewMigrationStatus
        weekly.bitwarden-desktop
        weekly.element-desktop
        weekly.libreoffice
        weekly.nextcloud-client
        pkgs.thunderbird
        pkgs.vlc
        weekly.bitwarden-cli
      ];
    activation.checkBrewProviders = lib.hm.dag.entryBefore ["writeBoundary"] ''
      if ! HOMEBREW_NO_AUTO_UPDATE=1 FINITE_BREW_POLICY=${./brew-packages.json} \
        ${brewMigrationStatus}/bin/finite-brew-migration-status --check-installed; then
        echo "Install the shared CLI tools before applying this profile:" >&2
        echo "  brew bundle install --no-upgrade --file=${brewFile}" >&2
        exit 1
      fi
    '';
  };

  fonts.fontconfig.enable = true;

  nix.package = null;

  targets.genericLinux = {
    enable = true;
    gpu.enable = true;
  };

  services.flatpak = {
    enable = true;
    uninstallUnmanaged = false;
    # Drop runtimes no installed application needs while preserving extra apps.
    uninstallUnused = true;
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
    firefox = {
      enable = true;
      package = finiteFirefox;
    };
    fzf.enable = true;
    git.enable = true;
    nh.enable = true;
    zsh = {
      enable = true;
      initContent = lib.mkBefore ''
        # Apply the shared CLI provider policy after Bluefin's global rc.
        path=(
          /home/linuxbrew/.linuxbrew/opt/uutils-coreutils/libexec/uubin
          /home/linuxbrew/.linuxbrew/bin
          /home/linuxbrew/.linuxbrew/sbin
          $path
        )
      '';
    };
  };

  xdg = {
    enable = true;
    configFile = {
      "finite/brew-packages.json".source = ./brew-packages.json;
      "finite/Brewfile".source = brewFile;
    };
  };
}
