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
      cachix
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
      secretspec
      shellcheck
      statix
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
  bluefin = config.purplefin.sources.bluefin;
  imageBuilder = config.purplefin.sources.imageBuilder;
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
          modules = [
            (den.lib.aspects.resolve "homeManager" config.purplefin.profiles.${name}.aspect)
            {
              home.sessionVariables.PURPLEFIN_PROFILE = profile.profileName;
              xdg.configFile."purplefin/profile.json".text = builtins.toJSON {
                inherit
                  (profile)
                  hardware
                  modules
                  parent
                  roles
                  tags
                  ;
              };
            }
          ];
        }
    )
    profiles;
  homeCheck = pkgs.runCommand "purplefin-home-configurations-proof" {} ''
    ${lib.concatStringsSep "\n" (
      lib.mapAttrsToList (_name: configuration: ''
        test -e ${configuration.activationPackage}
      '')
      homeConfigurations
    )}
    touch "$out"
  '';
  applications = import ../lib/flake-applications.nix {
    inherit bluefin generated imageBuilder pkgs version;
  };
  repositoryChecks = import ../lib/repository-checks.nix {
    inherit applications architecture generated lib pkgs;
  };
  formattingValidation = treefmtEval.config.build.check inputs.self;
  formattingCheck = pkgs.runCommand "purplefin-formatting-proof" {} ''
    test -e ${formattingValidation}
    touch "$out"
  '';
  architectureCheck = pkgs.runCommand "purplefin-architecture-proof" {} ''
    test -f ${architecture}/architecture.md
    test -f ${architecture}/namespace.mmd
    touch "$out"
  '';
  profileSchemaCheck = pkgs.runCommand "purplefin-profile-schema-proof" {} ''
    test -f ${generated}/bootc/generated/image-matrix.json
    test -f ${generated}/bootc/generated/profile-catalog.json
    test -f ${generated}/installer/config/profiles/base-generic.toml
    touch "$out"
  '';
  checks =
    repositoryChecks
    // {
      formatting = formattingCheck;
      architecture = architectureCheck;
      home-configurations = homeCheck;
      profile-schema = profileSchemaCheck;
    };
  ci = applications.mkCi checks;
  localCache = applications.mkLocalCache ci;
in {
  flake = {
    lib.purplefin = {
      inherit profiles;
      profileOrder = profileSet.order;
    };

    inherit homeConfigurations;
    packages.${system} =
      {
        inherit architecture;
        inherit ci;
        default = generated;
        inherit generated;
        workflow-ci = applications.workflowCi;
        workflow-image = applications.workflowImage;
        workflow-installer = applications.workflowInstaller;
        workflow-maintenance = applications.workflowMaintenance;
        workflow-release = applications.workflowRelease;
        inherit (pkgs) sbomnix syft;
      }
      // lib.mapAttrs' (
        name: configuration: lib.nameValuePair "home-${name}" configuration.activationPackage
      )
      homeConfigurations;

    apps.${system} = {
      ci = {
        type = "app";
        program = "${ci}/bin/purplefin-ci";
      };
      classify-changes = {
        type = "app";
        program = "${applications.classifyChanges}/bin/purplefin-classify-changes";
      };
      classify-ci = {
        type = "app";
        program = "${applications.classifyCi}/bin/purplefin-classify-ci";
      };
      release-notes = {
        type = "app";
        program = "${applications.releaseNotes}/bin/purplefin-release-notes";
      };
      trusted-update = {
        type = "app";
        program = "${applications.trustedUpdate}/bin/purplefin-trusted-update";
      };
      queue-dependabot = {
        type = "app";
        program = "${applications.queueDependabot}/bin/purplefin-queue-dependabot";
      };
      package-cleanup = {
        type = "app";
        program = "${applications.packageCleanup}/bin/purplefin-package-cleanup";
      };
      image-plan = {
        type = "app";
        program = "${applications.imagePlan}/bin/purplefin-image-plan";
      };
      ci-plan = {
        type = "app";
        program = "${applications.ciPlan}/bin/purplefin-ci-plan";
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
      installer-build = {
        type = "app";
        program = "${applications.installerBuild}/bin/purplefin-installer-build";
      };
      local-cache = {
        type = "app";
        program = "${localCache}/bin/purplefin-local-cache";
      };
      load-bluefin = {
        type = "app";
        program = "${applications.loadBluefin}/bin/purplefin-load-bluefin";
      };
      source-update = {
        type = "app";
        program = "${applications.sourceUpdate}/bin/purplefin-source-update";
      };
      source-verify = {
        type = "app";
        program = "${applications.sourceVerify}/bin/purplefin-source-verify";
      };
    };

    checks.${system} = checks;

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
