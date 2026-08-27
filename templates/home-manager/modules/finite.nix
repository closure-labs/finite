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
  hardwareNames = ["generic-x86_64" "dell-xps-9350-intel"];
  canonicalRoles = builtins.filter (role: builtins.elem role vars.roles) roleOrder;
  validProfile =
    vars.schema
    == 1
    && builtins.elem vars.foundation ["bluefin" "bluefin-dx"]
    && builtins.elem vars.hardware hardwareNames
    && builtins.length vars.roles == builtins.length canonicalRoles
    && builtins.length vars.roles == builtins.length (lib.unique vars.roles)
    && builtins.match "[a-z_][a-z0-9_-]*[$]?" vars.identity.username != null
    && builtins.match "/.+" vars.identity.homeDirectory != null;
  pkgs = import inputs.nixpkgs {
    inherit system;
    config.allowUnfree = true;
  };
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
in
  if !validProfile
  then throw "The local Finite profile is invalid or is not canonically ordered."
  else {
    den.homes.${system}.finite = {
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
            packages = [configure homeApply];
            sessionVariables = {
              FINITE_FOUNDATION = vars.foundation;
              FINITE_HARDWARE = vars.hardware;
              FINITE_ROLES = lib.concatStringsSep "," canonicalRoles;
            };
          };
          imports = [./local.nix];
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
