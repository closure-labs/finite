{
  config,
  inputs,
  lib,
  ...
}: let
  inherit (config) den;
  system = "x86_64-linux";
  pkgs = import inputs.nixpkgs {
    inherit system;
    config.allowUnfree = true;
  };
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
  bluefinDx = config.purplefin.sources.bluefinDx;
  homeProfiles = config.purplefin.homeProfiles;
  imageBuilder = config.purplefin.sources.imageBuilder;
  determinateNix = config.purplefin.sources.determinateNix;
  determinateNixInstaller = pkgs.fetchurl {
    name = "determinate-nix-installer-${determinateNix.version}";
    inherit (determinateNix.installer) url sha256;
  };
  determinateNixSelinuxPolicy = pkgs.fetchurl {
    name = "determinate-nix-selinux-policy-${determinateNix.version}";
    inherit (determinateNix.selinuxPolicy) url sha256;
  };
  determinateNixSelinuxFileContexts = pkgs.fetchurl {
    name = "determinate-nix-selinux-file-contexts-${determinateNix.version}";
    inherit (determinateNix.selinuxFileContexts) url sha256;
  };
  version = lib.removeSuffix "\n" (builtins.readFile ../VERSION);
  generated = import ../lib/render-profile-artifacts.nix {
    inherit determinateNixInstaller determinateNixSelinuxFileContexts determinateNixSelinuxPolicy homeProfiles lib pkgs profiles;
    profileOrder = profileSet.order;
    inherit version;
  };
  architecture = import ../lib/render-architecture.nix {
    inherit den lib pkgs;
    diagram = inputs.den-diagram.lib;
  };
  mkHomeConfiguration = {
    name,
    username ? "purplefin",
    homeDirectory ? "/var/home/${username}",
    hardware ? builtins.head homeProfiles.${name}.hardware,
  }: let
    profile = homeProfiles.${name};
    hardwareModule =
      if hardware == "dell-xps-9350-intel"
      then [(den.lib.aspects.resolve "homeManager" den.aspects.features.hardware.dell-xps-9350-intel)]
      else [];
  in
    assert builtins.elem hardware profile.hardware;
      inputs.home-manager.lib.homeManagerConfiguration {
        inherit pkgs;
        extraSpecialArgs = {inherit inputs;};
        modules =
          [
            (den.lib.aspects.resolve "homeManager" profile.aspect)
            {
              home = {
                inherit homeDirectory username;
                sessionVariables = {
                  PURPLEFIN_PROFILE = name;
                  PURPLEFIN_BASE_CLASS = profile.baseClass;
                  PURPLEFIN_HARDWARE = hardware;
                };
              };
              xdg.configFile."purplefin/profile.json".text = builtins.toJSON {
                inherit hardware name;
                inherit (profile) baseClass roles;
              };
            }
          ]
          ++ hardwareModule;
      };
  homeConfigurations = lib.mapAttrs (name: _: mkHomeConfiguration {inherit name;}) homeProfiles;
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
    inherit bluefin bluefinDx determinateNix generated imageBuilder pkgs version;
    selfSource = inputs.self;
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
    test -f ${generated}/bootc/generated/home-profile-catalog.json
    test -f ${generated}/installer/config/profiles/bluefin-generic.toml
    test -f ${generated}/installer/config/profiles/base-generic.toml
    test -f ${generated}/installer/config/profiles/base-generic-x86_64.toml
    cmp \
      ${generated}/installer/config/profiles/bluefin-generic.toml \
      ${generated}/installer/config/profiles/base-generic.toml
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
      inherit homeProfiles mkHomeConfiguration profiles;
      profileOrder = profileSet.order;
    };

    inherit homeConfigurations;
    packages.${system} =
      {
        inherit architecture;
        inherit ci;
        default = generated;
        inherit generated;
        workflow-installer = applications.workflowInstaller;
        workflow-gate = applications.workflowGate;
        workflow-prepare = applications.workflowPrepare;
        workflow-publish = applications.workflowPublish;
        workflow-release = applications.workflowRelease;
        workflow-sbom = applications.workflowSbom;
        workflow-validation = applications.workflowValidation;
        inherit (pkgs) syft;
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
      github-actions-secrets = {
        type = "app";
        program = "${applications.githubActionsSecrets}/bin/purplefin-github-actions-secrets";
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
      ci-gate = {
        type = "app";
        program = "${applications.ciGate}/bin/purplefin-ci-gate";
      };
      promote-images = {
        type = "app";
        program = "${applications.promoteImages}/bin/purplefin-promote-images";
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
      image-sign = {
        type = "app";
        program = "${applications.imageSign}/bin/purplefin-image-sign";
      };
      image-sbom = {
        type = "app";
        program = "${applications.imageSbom}/bin/purplefin-image-sbom";
      };
      sbom-attestation = {
        type = "app";
        program = "${applications.sbomAttestation}/bin/purplefin-sbom-attestation";
      };
      validate-image-shard = {
        type = "app";
        program = "${applications.validateImageShard}/bin/purplefin-validate-image-shard";
      };
      image-build = {
        type = "app";
        program = "${applications.imageBuild}/bin/purplefin-image-build";
      };
      home-switch = {
        type = "app";
        program = "${applications.homeSwitch}/bin/purplefin-home-switch";
      };
      cloud-init = {
        type = "app";
        program = "${applications.cloudInit}/bin/purplefin-cloud-init";
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
