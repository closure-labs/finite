{
  config,
  inputs,
  lib,
  ...
}: let
  inherit (config) den;
  system = "x86_64-linux";
  pkgs = import inputs.nixpkgs {inherit system;};
  profileSet = import ../lib/profile-set.nix {inherit den lib;};
  inherit (profileSet) profiles;
  generated = import ../lib/generated.nix {
    inherit lib pkgs profiles;
    profileOrder = profileSet.order;
    version = lib.removeSuffix "\n" (builtins.readFile ../../VERSION);
  };
  homeConfigurations =
    lib.mapAttrs (
      name: profile:
        inputs.home-manager.lib.homeManagerConfiguration {
          inherit pkgs;
          extraSpecialArgs = {inherit profile;};
          modules = [(den.lib.aspects.resolve "homeManager" den.aspects.profiles.${name})];
        }
    )
    profiles;
  generatedCurrent = pkgs.runCommand "purplefin-generated-files-current" {} ''
    diff -u ${generated}/bootc/generated/image-matrix.json ${inputs.self}/bootc/generated/image-matrix.json
    diff -u ${generated}/bootc/generated/profile-catalog.json ${inputs.self}/bootc/generated/profile-catalog.json
    diff -u ${generated}/bootc/generated/upstream.json ${inputs.self}/bootc/generated/upstream.json
    ${lib.concatStringsSep "\n" (
      lib.mapAttrsToList (name: _profile: ''
        diff -u ${generated}/installer/config/profiles/${name}.toml ${inputs.self}/installer/config/profiles/${name}.toml
      '')
      profiles
    )}
    touch "$out"
  '';
  homeCheck = pkgs.runCommand "purplefin-home-configurations" {} ''
    mkdir -p "$out"
    ${lib.concatStringsSep "\n" (
      lib.mapAttrsToList (name: configuration: ''
        ln -s ${configuration.activationPackage} "$out/${name}"
      '')
      homeConfigurations
    )}
  '';
  generateApp = pkgs.writeShellApplication {
    name = "purplefin-generate";
    runtimeInputs = [pkgs.coreutils];
    text = ''
      repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" && -d "''${repo_root}/bootc" ]] || {
        echo "Run this command from the Purplefin repository root" >&2
        exit 2
      }

      while IFS= read -r relative_path; do
        install -D -m 0644 \
          "${generated}/''${relative_path}" \
          "''${repo_root}/''${relative_path}"
      done <<'PATHS'
      bootc/generated/image-matrix.json
      bootc/generated/profile-catalog.json
      bootc/generated/upstream.json
      ${lib.concatStringsSep "\n" (
        lib.concatMap (name: [
          "installer/config/profiles/${name}.toml"
        ]) (lib.attrNames profiles)
      )}
      PATHS
    '';
  };
in {
  flake = {
    lib.purplefin = {
      inherit profiles;
      profileOrder = profileSet.order;
    };

    inherit homeConfigurations;
    homeManagerModules.default = ../aspects/base/home.nix;

    packages.${system} =
      {
        default = generated;
        inherit generated;
      }
      // lib.mapAttrs' (
        name: configuration: lib.nameValuePair "home-${name}" configuration.activationPackage
      )
      homeConfigurations;

    apps.${system} = {
      default = {
        type = "app";
        program = "${generateApp}/bin/purplefin-generate";
      };
      generate = {
        type = "app";
        program = "${generateApp}/bin/purplefin-generate";
      };
    };

    checks.${system} = {
      generated-current = generatedCurrent;
      home-configurations = homeCheck;
      profile-schema = generated;
    };

    devShells.${system} = {
      default = pkgs.mkShell {
        packages = with pkgs; [
          actionlint
          alejandra
          deadnix
          just
          pipewire
          ripgrep
          shellcheck
          zsh
          zizmor
        ];
      };
      installer = pkgs.mkShell {
        packages = [pkgs.qemu];
      };
    };

    formatter.${system} = pkgs.alejandra;
  };
}
