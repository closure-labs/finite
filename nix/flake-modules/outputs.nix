{
  config,
  inputs,
  lib,
  ...
}: let
  inherit (config) den;
  system = "x86_64-linux";
  pkgs = import inputs.nixpkgs {inherit system;};
  treefmtEval = inputs.treefmt-nix.lib.evalModule pkgs ../../treefmt.nix;
  repositoryToolchain =
    (with pkgs; [
      actionlint
      bash
      coreutils
      diffutils
      file
      findutils
      gawk
      git
      glib
      gnugrep
      gnused
      jq
      just
      pipewire
      ripgrep
      shellcheck
      systemd
      util-linux
      zizmor
      zsh
    ])
    ++ [treefmtEval.config.build.wrapper];
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
  mkRepositoryApp = {
    name,
    script,
    runtimeInputs,
  }:
    pkgs.writeShellApplication {
      inherit name runtimeInputs;
      text = ''
        repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
        [[ -f "''${repo_root}/flake.nix" ]] || {
          echo "Run this command from the Purplefin repository root" >&2
          exit 2
        }
        cd "''${repo_root}"
        exec ${pkgs.bash}/bin/bash "''${repo_root}/${script}" "$@"
      '';
    };
  ciApp = mkRepositoryApp {
    name = "purplefin-ci";
    script = "tests/ci.sh";
    runtimeInputs = repositoryToolchain;
  };
  changedComponentApp = mkRepositoryApp {
    name = "purplefin-changed-component";
    script = "ci/changed-component.sh";
    runtimeInputs = with pkgs; [bash coreutils gnugrep gnused];
  };
  releaseNotesApp = mkRepositoryApp {
    name = "purplefin-release-notes";
    script = "ci/release-notes.sh";
    runtimeInputs = with pkgs; [bash coreutils gawk gnugrep gnused];
  };
  trustedUpdateApp = mkRepositoryApp {
    name = "purplefin-trusted-update";
    script = "ci/validate-trusted-update.sh";
    runtimeInputs = with pkgs; [bash coreutils gh jq];
  };
  imagePlanApp = mkRepositoryApp {
    name = "purplefin-image-plan";
    script = "bootc/build/plan.sh";
    runtimeInputs = with pkgs; [bash coreutils cosign jq podman skopeo];
  };
  imageReuseApp = mkRepositoryApp {
    name = "purplefin-image-reuse";
    script = "bootc/build/reuse-image.sh";
    runtimeInputs = with pkgs; [bash coreutils cosign jq skopeo];
  };
  installerSmokeApp = mkRepositoryApp {
    name = "purplefin-installer-smoke";
    script = "tests/boot-installer-iso.sh";
    runtimeInputs = with pkgs; [bash coreutils gnugrep qemu];
  };
  imageBuildApp = pkgs.writeShellApplication {
    name = "purplefin-image-build";
    runtimeInputs = with pkgs; [bash coreutils jq just podman skopeo];
    text = ''
      repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Purplefin repository root" >&2
        exit 2
      }
      (( $# == 2 )) || {
        echo "usage: nix run .#image-build -- PROFILE IMAGE_TAG" >&2
        exit 2
      }
      cd "''${repo_root}"
      exec ${pkgs.just}/bin/just _build "$1" "$2"
    '';
  };
  repositoryCheck =
    pkgs.runCommand "purplefin-repository-checks" {
      nativeBuildInputs = repositoryToolchain;
    } ''
      export HOME="$TMPDIR/home"
      mkdir -p "$HOME" source
      cp -R ${inputs.self}/. source/
      chmod -R u+w source
      cd source
      substituteInPlace Justfile \
        --replace-fail '#!/usr/bin/env bash' '#!${pkgs.bash}/bin/bash'
      PURPLEFIN_HERMETIC_CHECK=true PURPLEFIN_SOURCE_ROOT="$PWD" ${ciApp}/bin/purplefin-ci
      touch "$out"
    '';
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
        ci = ciApp;
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
      check = {
        type = "app";
        program = "${ciApp}/bin/purplefin-ci";
      };
      ci = {
        type = "app";
        program = "${ciApp}/bin/purplefin-ci";
      };
      changed-component = {
        type = "app";
        program = "${changedComponentApp}/bin/purplefin-changed-component";
      };
      release-notes = {
        type = "app";
        program = "${releaseNotesApp}/bin/purplefin-release-notes";
      };
      trusted-update = {
        type = "app";
        program = "${trustedUpdateApp}/bin/purplefin-trusted-update";
      };
      image-plan = {
        type = "app";
        program = "${imagePlanApp}/bin/purplefin-image-plan";
      };
      image-reuse = {
        type = "app";
        program = "${imageReuseApp}/bin/purplefin-image-reuse";
      };
      image-build = {
        type = "app";
        program = "${imageBuildApp}/bin/purplefin-image-build";
      };
      installer-smoke = {
        type = "app";
        program = "${installerSmokeApp}/bin/purplefin-installer-smoke";
      };
    };

    checks.${system} = {
      formatting = treefmtEval.config.build.check inputs.self;
      generated-current = generatedCurrent;
      home-configurations = homeCheck;
      profile-schema = generated;
      repository = repositoryCheck;
    };

    devShells.${system} = {
      default = pkgs.mkShell {
        packages = repositoryToolchain;
      };
      installer = pkgs.mkShell {
        packages = [pkgs.qemu];
      };
    };

    formatter.${system} = treefmtEval.config.build.wrapper;
  };
}
