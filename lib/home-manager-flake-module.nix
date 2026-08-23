{
  finiteInputs,
  homeBootstrap,
  homeProfile,
}: {
  config,
  den,
  lib,
  ...
}: let
  cfg = config.finite.homeProfile;
  system = "x86_64-linux";
  roleOrder = ["developer" "sales" "trainer" "support" "executive" "it"];
  canonicalRoles = builtins.filter (role: builtins.elem role cfg.roles) roleOrder;
  configure = cfgPkgs.writeTextFile {
    name = "finite-configure";
    destination = "/bin/finite-configure";
    executable = true;
    text = ''
      #!${cfgPkgs.zsh}/bin/zsh
      set -euo pipefail
      export PATH=${lib.makeBinPath [cfgPkgs.coreutils cfgPkgs.jq cfgPkgs.zenity]}

      running=/usr/share/finite/profile.json
      if [[ ! -r $running ]]; then
        zenity --error --title='Finite configuration' --text='The running Finite profile metadata is unavailable.'
        exit 1
      fi
      foundation=$(jq -er '.foundation' $running)
      hardware=$(jq -er '.hardware' $running)
      current=$HOME/.config/finite/profile.json
      selected=()
      if [[ -r $current ]]; then
        selected=($(jq -r '.roles[]' $current))
      fi
      rows=()
      for entry in \
        developer:Developer sales:Sales trainer:Trainer support:Support executive:Executive it:IT; do
        role=''${entry%%:*}
        label=''${entry#*:}
        checked=FALSE
        (( ''${selected[(Ie)$role]} )) && checked=TRUE
        rows+=("$checked" "$label" "$role")
      done
      roles=$(zenity --list --checklist \
        --title='Configure Finite' \
        --text='Select any roles to compose with your Finite foundation.' \
        --column='Use' --column='Role' --column='id' \
        --hide-column=3 --separator=, "''${rows[@]}") || exit 0
      profile=$(mktemp)
      trap 'rm -f -- "$profile"' EXIT
      ${homeProfile}/bin/finite-home-profile \
        --foundation "$foundation" --hardware "$hardware" \
        --roles "$roles" --format yaml >$profile
      exec ${homeBootstrap}/bin/finite-home-bootstrap --profile "$profile"
    '';
  };
  cfgPkgs = import finiteInputs.nixpkgs {
    inherit system;
    config.allowUnfree = true;
  };
in {
  options.finite.homeProfile = lib.mkOption {
    description = "Normalized Finite standalone Home Manager profile.";
    type = lib.types.submodule {
      options = {
        schema = lib.mkOption {type = lib.types.enum [1];};
        foundation = lib.mkOption {type = lib.types.enum ["bluefin" "bluefin-dx"];};
        hardware = lib.mkOption {type = lib.types.enum ["generic-x86_64" "dell-xps-9350-intel"];};
        roles = lib.mkOption {
          type = lib.types.listOf (lib.types.enum roleOrder);
          default = [];
          apply = roles: assert lib.length roles == lib.length (lib.unique roles); roles;
        };
        identity = {
          username = lib.mkOption {type = lib.types.strMatching "[a-z_][a-z0-9_-]*[$]?";};
          homeDirectory = lib.mkOption {type = lib.types.strMatching "/.+";};
        };
      };
    };
  };

  config = {
    den.homes.${system}.finite = {
      userName = cfg.identity.username;
      pkgs = cfgPkgs;
      aspect = den.aspects.finite-home;
      instantiate = {
        pkgs,
        modules,
      }:
        finiteInputs.home-manager.lib.homeManagerConfiguration {
          inherit modules pkgs;
          extraSpecialArgs.inputs = finiteInputs;
        };
    };

    den.aspects.finite-home = {
      includes =
        [den.aspects.features.base]
        ++ map (role: den.aspects.features.roles.${role}) canonicalRoles
        ++ [den.aspects.features.hardware.${cfg.hardware}];
      homeManager = {
        home = {
          username = lib.mkForce cfg.identity.username;
          homeDirectory = lib.mkForce cfg.identity.homeDirectory;
          packages = [configure];
          sessionVariables = {
            FINITE_FOUNDATION = cfg.foundation;
            FINITE_HARDWARE = cfg.hardware;
            FINITE_ROLES = lib.concatStringsSep "," canonicalRoles;
          };
        };
        programs = {
          nh.homeFlake = "path:${cfg.identity.homeDirectory}/.config/home-manager";
          zsh.shellAliases.finite-configure = "${configure}/bin/finite-configure";
        };
      };
    };
  };
}
