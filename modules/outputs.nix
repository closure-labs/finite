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
  fedoraBootc = config.purplefin.sources.fedoraBootc;
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
    sourceFlake ? "github:declarative-dale/purplefin",
  }: let
    profile = homeProfiles.${name};
    homeDriverFlake = pkgs.writeText "purplefin-home-flake.nix" ''
      {
        inputs.purplefin.url = ${builtins.toJSON sourceFlake};

        outputs = { purplefin, ... }: {
          homeConfigurations = {
            ${builtins.toJSON username} =
              purplefin.lib.purplefin.mkHomeConfiguration {
                name = ${builtins.toJSON name};
                hardware = ${builtins.toJSON hardware};
                username = ${builtins.toJSON username};
                homeDirectory = ${builtins.toJSON homeDirectory};
                sourceFlake = ${builtins.toJSON sourceFlake};
              };
          };
        };
      }
    '';
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
            ({
              config,
              lib,
              ...
            }: {
              home = {
                inherit homeDirectory username;
                sessionVariables = {
                  PURPLEFIN_PROFILE = name;
                  PURPLEFIN_BASE_CLASS = profile.baseClass;
                  PURPLEFIN_HARDWARE = hardware;
                };
              };
              home.activation.writePurplefinHomeFlake = lib.hm.dag.entryAfter ["linkGeneration"] ''
                driver_dir=${lib.escapeShellArg "${config.xdg.configHome}/purplefin/home"}
                driver_file="''${driver_dir}/flake.nix"
                run ${pkgs.coreutils}/bin/mkdir -p "''${driver_dir}"
                if [[ -L "''${driver_file}" ]]; then
                  run ${pkgs.coreutils}/bin/rm -f "''${driver_file}"
                fi
                if ! ${pkgs.diffutils}/bin/cmp -s ${homeDriverFlake} "''${driver_file}"; then
                  run ${pkgs.coreutils}/bin/install -m 0644 ${homeDriverFlake} "''${driver_file}"
                fi
              '';
              programs.nh.homeFlake = "path:${config.xdg.configHome}/purplefin/home";
              xdg.configFile."purplefin/profile.json".text = builtins.toJSON {
                inherit hardware name;
                inherit (profile) baseClass roles;
              };
            })
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
    devenv = inputs.devenv.packages.${system}.devenv;
    inherit bluefin bluefinDx determinateNix fedoraBootc generated imageBuilder pkgs version;
    selfSource = inputs.self;
  };
  repositoryChecks = import ../lib/repository-checks.nix {
    inherit applications architecture generated lib pkgs;
  };
  formattingSource = lib.cleanSourceWith {
    src = inputs.self;
    filter = path: _type: let
      relative = lib.removePrefix "${toString inputs.self}/" (toString path);
    in
      relative
      != ".devenv"
      && !(lib.hasPrefix ".devenv/" relative)
      && relative != ".direnv"
      && !(lib.hasPrefix ".direnv/" relative);
  };
  formattingValidation = treefmtEval.config.build.check formattingSource;
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
  ciChecks = pkgs.runCommand "purplefin-ci-checks" {} ''
    mkdir "$out"
    ${lib.concatStringsSep "\n" (
      lib.mapAttrsToList (name: check: ''
        ln -s ${check} "$out/${name}"
      '')
      checks
    )}
  '';
  ciCheck = applications.mkCheck checks;
  localCache = applications.mkLocalCache ciCheck;
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
        ci-check = ciCheck;
        ci-checks = ciChecks;
        ci-prepare = applications.ciPrepare;
        ci-validate-plan = applications.validateCiPlan;
        ci-gate = applications.ciGate;
        ci-validate-image-shard = applications.validateImageShard;
        ci-image-reuse = applications.imageReuse;
        ci-image-sign = applications.imageSign;
        ci-image-build = applications.imageBuild;
        ci-image-sbom = applications.imageSbom;
        ci-sbom-attestation = applications.sbomAttestation;
        ci-promote-images = applications.promoteImages;
        ci-installer-build = applications.installerBuild;
        ci-installer-e2e = applications.installerE2e;
        ci-installer-smoke = applications.installerSmoke;
        ci-release-notes = applications.releaseNotes;
        ci-update-locks = applications.updateLocks;
        ci-source-update = applications.sourceUpdate;
        ci-source-verify = applications.sourceVerify;
        ci-trusted-update = applications.trustedUpdate;
        ci-queue-dependabot = applications.queueDependabot;
        ci-package-cleanup = applications.packageCleanup;
        ci-github-actions-secrets = applications.githubActionsSecrets;
        ci-load-bluefin = applications.loadBluefin;
        ci-lock-validate = applications.validateLocks;
        ci-cosign = pkgs.cosign;
        ci-oras = pkgs.oras;
        ci-skopeo = pkgs.skopeo;
        devenv = inputs.devenv.packages.${system}.devenv;
        default = generated;
        inherit generated;
        inherit (pkgs) syft;
      }
      // lib.mapAttrs' (
        name: configuration: lib.nameValuePair "home-${name}" configuration.activationPackage
      )
      homeConfigurations;

    apps.${system} = {
      devenv = {
        type = "app";
        program = lib.getExe inputs.devenv.packages.${system}.devenv;
      };
      home-switch = {
        type = "app";
        program = "${applications.homeSwitch}/bin/purplefin-home-switch";
      };
      cloud-init = {
        type = "app";
        program = "${applications.cloudInit}/bin/purplefin-cloud-init";
      };
      local-cache = {
        type = "app";
        program = "${localCache}/bin/purplefin-local-cache";
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
