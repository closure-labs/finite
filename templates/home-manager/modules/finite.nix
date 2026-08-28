{
  den,
  inputs,
  lib,
  ...
}: let
  # Bootstrap writes these local profile variables before the flake is built.
  vars = builtins.fromJSON (builtins.readFile ../profile.json);
  system = "x86_64-linux";
  roleOrder = ["developer" "sales" "trainer" "support" "executive" "it"];
  packageOrder = ["hack-font" "herdr" "jj" "opencode" "uv"];
  hardwareNames = ["generic-x86_64" "dell-xps-9350-intel"];
  canonicalRoles = builtins.filter (role: builtins.elem role vars.roles) roleOrder;
  canonicalPackages = builtins.filter (package: builtins.elem package vars.packages) packageOrder;
  validProfile =
    vars.schema
    == 2
    && builtins.elem vars.foundation ["bluefin" "bluefin-dx"]
    && builtins.elem vars.hardware hardwareNames
    && builtins.length vars.roles == builtins.length canonicalRoles
    && builtins.length vars.roles == builtins.length (lib.unique vars.roles)
    && builtins.length vars.packages == builtins.length canonicalPackages
    && builtins.length vars.packages == builtins.length (lib.unique vars.packages)
    && builtins.match "[a-z_][a-z0-9_-]*[$]?" vars.identity.username != null
    && builtins.match "/.+" vars.identity.homeDirectory != null;
  pkgs = import inputs.nixpkgs {
    inherit system;
    config.allowUnfree = true;
  };
  weekly = inputs.nixpkgs-weekly.legacyPackages.${system};
  optionalPackages = {
    "hack-font" = pkgs.nerd-fonts.hack;
    inherit (weekly) herdr;
    jj = pkgs.jujutsu;
    inherit (pkgs) opencode uv;
  };
  selectedPackages = map (name: optionalPackages.${name}) canonicalPackages;
  homeApply = pkgs.writeShellApplication {
    name = "finite-home-apply";
    runtimeInputs = with pkgs; [coreutils getent jq];
    text = builtins.readFile ./finite-home-apply;
  };
  configure = pkgs.writeShellApplication {
    name = "finite-configure";
    runtimeInputs = with pkgs; [coreutils jq zenity homeApply];
    text = builtins.readFile ./finite-configure;
  };
  brewMigrationStatus = pkgs.writeShellApplication {
    name = "finite-brew-migration-status";
    runtimeInputs = with pkgs; [coreutils gnugrep];
    text = builtins.readFile ./finite-brew-migration-status;
  };
in
  if !validProfile
  then throw "The local Finite profile is invalid or is not canonically ordered."
  else {
    den.homes.${system}.${vars.identity.username} = {
      userName = vars.identity.username;
      inherit pkgs;
      aspect = den.aspects.finite-home;
      instantiate = {
        modules,
        pkgs,
        ...
      }:
        inputs.home-manager.lib.homeManagerConfiguration {
          inherit modules pkgs;
          extraSpecialArgs = {
            inherit inputs;
            finiteHomeAssets = {
              devops = ./aspects/capabilities/devops/rootfs/usr/share/finite;
            };
          };
        };
    };

    den.aspects = {
      finite-home = {
        includes =
          [den.aspects.features.base]
          ++ map (role: den.aspects.features.roles.${role}) canonicalRoles
          ++ [den.aspects.features.hardware.${vars.hardware}];
        homeManager = {
          home = {
            username = lib.mkForce vars.identity.username;
            homeDirectory = lib.mkForce vars.identity.homeDirectory;
            packages = [brewMigrationStatus configure homeApply] ++ selectedPackages;
            sessionVariables = {
              FINITE_FOUNDATION = vars.foundation;
              FINITE_HARDWARE = vars.hardware;
              FINITE_PACKAGES = lib.concatStringsSep "," canonicalPackages;
              FINITE_ROLES = lib.concatStringsSep "," canonicalRoles;
            };
          };
          imports = [../customize.nix ./local.nix];
          programs = {
            nh.homeFlake = "path:${vars.identity.homeDirectory}/.config/home-manager";
            zsh.shellAliases.finite-configure = "${configure}/bin/finite-configure";
          };
        };
      };

      features = {
        base.homeManager.imports = [./aspects/base/home.nix];
        capabilities.devops.homeManager.imports = [./aspects/capabilities/devops/home.nix];
        roles = {
          developer = {
            includes = [den.aspects.features.capabilities.devops];
            homeManager.imports = [./aspects/roles/developer/home.nix];
          };
          sales.homeManager.imports = [./aspects/roles/sales/home.nix];
          trainer.homeManager.imports = [./aspects/roles/trainer/home.nix];
          support = {
            includes = [den.aspects.features.capabilities.devops];
            homeManager.imports = [./aspects/roles/support/home.nix];
          };
          executive.homeManager.imports = [./aspects/roles/executive/home.nix];
          it.homeManager.imports = [./aspects/roles/it/home.nix];
        };
        hardware = {
          generic-x86_64.homeManager.imports = [./aspects/hardware/generic-x86_64/home.nix];
          dell-xps-9350-intel.homeManager.imports = [./aspects/hardware/dell-xps-9350-intel/home.nix];
        };
      };
    };
  }
