{
  config,
  inputs,
  lib,
  ...
}: let
  inherit (config) den;
  system = "x86_64-linux";
  pkgs = import inputs.nixpkgs {inherit system;};
  treefmtEval = inputs.treefmt-nix.lib.evalModule pkgs ../treefmt.nix;
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
  profileSet = import ../lib/eval-profile-graph.nix {
    inherit den lib;
    profileEntities = config.purplefin.profiles;
  };
  inherit (profileSet) profiles;
  version = lib.removeSuffix "\n" (builtins.readFile ../VERSION);
  generated = import ../lib/render-profile-artifacts.nix {
    inherit lib pkgs profiles;
    profileOrder = profileSet.order;
    inherit version;
  };
  architecture = import ../lib/render-architecture.nix {
    inherit den lib pkgs;
    diagram = inputs.den-diagram.lib;
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
  homeCheck = pkgs.runCommand "purplefin-home-configurations" {} ''
    mkdir -p "$out"
    ${lib.concatStringsSep "\n" (
      lib.mapAttrsToList (name: configuration: ''
        ln -s ${configuration.activationPackage} "$out/${name}"
      '')
      homeConfigurations
    )}
  '';
  applications = import ../lib/flake-applications.nix {
    inherit generated pkgs profiles repositoryToolchain version;
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
      PURPLEFIN_HERMETIC_CHECK=true PURPLEFIN_SOURCE_ROOT="$PWD" ${applications.ci}/bin/purplefin-ci
      grep -qF 'profiles_dale --> features_roles_support' ${architecture}/namespace.mmd
      touch "$out"
    '';
in {
  flake = {
    lib.purplefin = {
      inherit profiles;
      profileOrder = profileSet.order;
    };

    inherit homeConfigurations;
    homeManagerModules.default = ../home/base.nix;

    packages.${system} =
      {
        inherit architecture;
        ci = applications.ci;
        default = generated;
        inherit generated;
        inherit (pkgs) sbomnix syft;
      }
      // lib.mapAttrs' (
        name: configuration: lib.nameValuePair "home-${name}" configuration.activationPackage
      )
      homeConfigurations;

    apps.${system} = {
      export-artifacts = {
        type = "app";
        program = "${applications.exportArtifacts}/bin/purplefin-export-artifacts";
      };
      ci = {
        type = "app";
        program = "${applications.ci}/bin/purplefin-ci";
      };
      classify-changes = {
        type = "app";
        program = "${applications.classifyChanges}/bin/purplefin-classify-changes";
      };
      release-notes = {
        type = "app";
        program = "${applications.releaseNotes}/bin/purplefin-release-notes";
      };
      trusted-update = {
        type = "app";
        program = "${applications.trustedUpdate}/bin/purplefin-trusted-update";
      };
      image-plan = {
        type = "app";
        program = "${applications.imagePlan}/bin/purplefin-image-plan";
      };
      image-reuse = {
        type = "app";
        program = "${applications.imageReuse}/bin/purplefin-image-reuse";
      };
      image-build = {
        type = "app";
        program = "${applications.imageBuild}/bin/purplefin-image-build";
      };
      installer-smoke = {
        type = "app";
        program = "${applications.installerSmoke}/bin/purplefin-installer-smoke";
      };
    };

    checks.${system} = {
      formatting = treefmtEval.config.build.check inputs.self;
      architecture = architecture;
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
