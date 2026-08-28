{
  catalog,
  homeBootstrap,
  homeDependencies,
  homeInputs,
  homeManagerLib,
  homeProfile,
  mkPkgs,
  project,
}: {
  config,
  den,
  lib,
  ...
}: let
  cfg = config.finite.homeProfile;
  system = project.platform.system;
  roleOrder = catalog.roleNames;
  packageOrder = catalog.packageNames;
  canonicalRoles = builtins.filter (role: builtins.elem role cfg.roles) roleOrder;
  canonicalPackages = builtins.filter (package: builtins.elem package cfg.packages) packageOrder;
  configureRoleRows =
    lib.concatMapStringsSep "\n" (
      role: ''
        checked=FALSE
        (( ''${selected[(Ie)${role.name}]} )) && checked=TRUE
        rows+=("$checked" ${lib.escapeShellArg role.label} ${lib.escapeShellArg role.name})
      ''
    )
    catalog.roles;
  configurePackageRows =
    lib.concatMapStringsSep "\n" (
      package: ''
        checked=FALSE
        (( ''${selected_packages[(Ie)${package.name}]} )) && checked=TRUE
        package_rows+=("$checked" ${lib.escapeShellArg package.label} ${lib.escapeShellArg package.description} ${lib.escapeShellArg package.name})
      ''
    )
    catalog.packages;
  configure = cfgPkgs.writeTextFile {
    name = "finite-configure";
    destination = "/bin/finite-configure";
    executable = true;
    text = ''
      #!${cfgPkgs.zsh}/bin/zsh
      set -euo pipefail
      export PATH=${lib.makeBinPath [cfgPkgs.coreutils cfgPkgs.jq cfgPkgs.zenity]}

      foundation=${lib.escapeShellArg cfg.foundation}
      hardware=${lib.escapeShellArg cfg.hardware}
      current=$HOME/.config/finite/profile.json
      selected=()
      selected_packages=()
      if [[ -r $current ]]; then
        selected=($(jq -r '.roles[]' $current))
        selected_packages=($(jq -r '(.packages // [])[]' $current))
      fi
      rows=()
      ${configureRoleRows}
      roles=$(zenity --list --checklist \
        --title='Configure Finite' \
        --text='Select any roles to compose with your Finite foundation.' \
        --column='Use' --column='Role' --column='id' \
        --hide-column=3 --print-column=3 --separator=, "''${rows[@]}") || exit 0
      package_rows=()
      ${configurePackageRows}
      packages=$(zenity --list --checklist \
        --title='Configure Finite packages' \
        --text='Select optional Nix packages. Finite builds the complete Home Manager generation before changing your profile.' \
        --column='Use' --column='Package' --column='Description' --column='id' \
        --hide-column=4 --print-column=4 --separator=, "''${package_rows[@]}") || exit 0
      profile=$(mktemp)
      trap 'rm -f -- "$profile"' EXIT
      ${homeProfile}/bin/finite-home-profile \
        --foundation "$foundation" --hardware "$hardware" \
        --packages "$packages" \
        --roles "$roles" --format yaml >$profile
      exec ${homeBootstrap}/bin/finite-home-bootstrap --profile "$profile"
    '';
  };
  cfgPkgs = mkPkgs system;
  weekly = homeDependencies.weeklyPackages;
  optionalPackages = {
    "hack-font" = cfgPkgs.nerd-fonts.hack;
    inherit (weekly) herdr;
    jj = cfgPkgs.jujutsu;
    inherit (cfgPkgs) opencode uv;
  };
  selectedPackages = map (name: optionalPackages.${name}) canonicalPackages;
in {
  options.finite.homeProfile = lib.mkOption {
    description = "Normalized Finite standalone Home Manager profile.";
    type = lib.types.submodule {
      options = {
        schema = lib.mkOption {type = lib.types.enum [2];};
        foundation = lib.mkOption {type = lib.types.enum catalog.foundationNames;};
        hardware = lib.mkOption {type = lib.types.enum catalog.homeHardwareNames;};
        roles = lib.mkOption {
          type = lib.types.listOf (lib.types.enum roleOrder);
          default = [];
          apply = roles: assert lib.length roles == lib.length (lib.unique roles); roles;
        };
        packages = lib.mkOption {
          type = lib.types.listOf (lib.types.enum packageOrder);
          default = [];
          apply = packages: assert lib.length packages == lib.length (lib.unique packages); packages;
        };
        identity = {
          username = lib.mkOption {type = lib.types.strMatching "[a-z_][a-z0-9_-]*[$]?";};
          homeDirectory = lib.mkOption {type = lib.types.strMatching "/.+";};
        };
      };
    };
  };

  config = {
    den.homes.${system}.${cfg.identity.username} = {
      userName = cfg.identity.username;
      pkgs = cfgPkgs;
      aspect = den.aspects.finite-home;
      instantiate = {
        pkgs,
        modules,
      }:
        homeManagerLib.homeManagerConfiguration {
          inherit modules pkgs;
          extraSpecialArgs = {
            finiteHomeDependencies = homeDependencies;
            finiteHomeAssets = {
              devops = ../templates/home-manager/modules/aspects/capabilities/devops/rootfs/usr/share/finite;
            };
            inputs = homeInputs;
          };
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
          packages = [configure] ++ selectedPackages;
          sessionVariables = {
            FINITE_FOUNDATION = cfg.foundation;
            FINITE_HARDWARE = cfg.hardware;
            FINITE_PACKAGES = lib.concatStringsSep "," canonicalPackages;
            FINITE_ROLES = lib.concatStringsSep "," canonicalRoles;
          };
        };
        fonts.fontconfig.enable = true;
        programs = {
          nh.homeFlake = "path:${cfg.identity.homeDirectory}/.config/home-manager";
          zsh.shellAliases.finite-configure = "${configure}/bin/finite-configure";
        };
      };
    };
  };
}
