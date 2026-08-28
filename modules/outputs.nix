{
  catalog,
  config,
  homeDependencies,
  lib,
  mkPkgs,
  outputDependencies,
  project,
  ...
}: let
  inherit (config) den;
  system = project.platform.system;
  pkgs = mkPkgs system;
  treefmtEval = outputDependencies.treefmt.evalModule pkgs ../treefmt.nix;
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
    inherit catalog lib project;
    profileEntities = config.finite.profiles;
    profileHosts = config.den.hosts.${system};
  };
  inherit (profileSet) profiles;
  bluefin = config.finite.sources.bluefin;
  bluefinDx = config.finite.sources.bluefinDx;
  home = config.finite.home;
  dakotaInstallerLock = builtins.fromJSON (builtins.readFile ../sources/dakota-installer.json);
  dakotaIsoSource = pkgs.fetchFromGitHub {
    inherit (dakotaInstallerLock.iso_source) owner;
    repo = dakotaInstallerLock.iso_source.repository;
    rev = dakotaInstallerLock.iso_source.revision;
    hash = dakotaInstallerLock.iso_source.hash;
  };
  bootcInstallerBundle = pkgs.fetchurl {
    name = "finite-bootc-installer-${dakotaInstallerLock.installer.version}.flatpak";
    inherit (dakotaInstallerLock.installer) url sha256;
  };
  determinateNix = config.finite.sources.determinateNix;
  inherit (project) cache;
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
  homeScaffold = import ../lib/render-home-scaffold.nix {
    inherit pkgs version;
  };
  generated = import ../lib/render-profile-artifacts.nix {
    inherit determinateNixInstaller determinateNixSelinuxFileContexts determinateNixSelinuxPolicy homeScaffold lib pkgs profiles;
    domainCatalog = catalog;
    profileOrder = profileSet.order;
    inherit version;
  };
  architecture = import ../lib/render-architecture.nix {
    inherit den lib pkgs;
    inherit (outputDependencies) diagram;
  };
  baseApplications = import ../lib/flake-applications.nix {
    devenv = outputDependencies.devenvPackage;
    inherit bluefin bluefinDx bootcInstallerBundle dakotaInstallerLock dakotaIsoSource determinateNix generated pkgs version;
    cacheName = cache.name;
    secretspec = outputDependencies.weeklySecretspec;
  };
  homeApplications = import ../lib/home-profile-applications.nix {inherit generated homeScaffold pkgs;};
  applications = baseApplications // homeApplications;
  roleModules = map (name: ../modules/aspects/roles + "/${name}/default.nix") catalog.roleNames;
  hardwareModules = map (name: ../modules/aspects/hardware + "/${name}/default.nix") catalog.homeHardwareNames;
  homeFlakeModule = {
    imports =
      [
        outputDependencies.denFlakeModule
        ../modules/sources/oci-locks.nix
        ../modules/aspects/base/default.nix
        ../modules/aspects/capabilities/devops/default.nix
      ]
      ++ roleModules
      ++ hardwareModules
      ++ [
        (import ../lib/home-manager-flake-module.nix {
          inherit catalog homeDependencies mkPkgs project;
          homeInputs = outputDependencies.homeModuleInputs;
          inherit (outputDependencies) homeManagerLib;
          inherit (applications) homeBootstrap homeProfile;
        })
      ];
  };
  allRoles = catalog.roleNames;
  mkHomeProof = foundation: hardware: packages: roles: let
    username = "finite-check-${foundation}-${hardware}-${lib.concatStringsSep "-" packages}-${lib.concatStringsSep "-" roles}";
    evaluated = lib.evalModules {
      # Den resolves its generated module imports from these Flake inputs.
      specialArgs.inputs = outputDependencies.homeModuleInputs;
      modules = [
        homeFlakeModule
        {
          finite.homeProfile = {
            schema = 2;
            inherit foundation hardware packages roles;
            identity = {
              inherit username;
              homeDirectory = "/var/home/${username}";
            };
          };
        }
      ];
    };
  in
    evaluated.config.flake.homeConfigurations.${username}.activationPackage;
  foundationHardwareProofs =
    lib.concatMap (
      foundation:
        map (hardware: mkHomeProof foundation hardware [] []) catalog.homeHardwareNames
    )
    catalog.foundationNames;
  roleProofs =
    map (
      role:
        mkHomeProof
        (builtins.head catalog.foundationNames)
        (builtins.head catalog.homeHardwareNames)
        []
        [role]
    )
    allRoles;
  allRolesProof =
    mkHomeProof
    (lib.last catalog.foundationNames)
    (lib.last catalog.homeHardwareNames)
    []
    allRoles;
  allPackagesProof =
    mkHomeProof
    (builtins.head catalog.foundationNames)
    (builtins.head catalog.homeHardwareNames)
    catalog.packageNames
    [];
  homeProofsEvaluated =
    builtins.deepSeq (
      map (activation: activation.drvPath) (foundationHardwareProofs ++ roleProofs ++ [allRolesProof allPackagesProof])
    )
    true;
  homeCheck = assert homeProofsEvaluated;
    pkgs.runCommand "finite-home-configurations-proof" {} ''
      touch "$out"
    '';
  repositoryChecks = import ../lib/repository-checks.nix {
    inherit applications architecture generated lib pkgs;
  };
  formattingSource = lib.cleanSourceWith {
    src = outputDependencies.self;
    filter = path: _type: let
      relative = lib.removePrefix "${toString outputDependencies.self}/" (toString path);
    in
      relative
      != ".git"
      && !(lib.hasPrefix ".git/" relative)
      && relative != ".devenv"
      && !(lib.hasPrefix ".devenv/" relative)
      && relative != ".direnv"
      && !(lib.hasPrefix ".direnv/" relative);
  };
  formattingValidation = treefmtEval.config.build.check formattingSource;
  formattingCheck = pkgs.runCommand "finite-formatting-proof" {} ''
    test -e ${formattingValidation}
    touch "$out"
  '';
  architectureCheck = pkgs.runCommand "finite-architecture-proof" {} ''
    test -f ${architecture}/architecture.md
    test -f ${architecture}/namespace.mmd
    touch "$out"
  '';
  profileSchemaCheck = pkgs.runCommand "finite-profile-schema-proof" {} ''
    test -f ${generated}/bootc/generated/image-matrix.json
    test -f ${generated}/bootc/generated/profile-catalog.json
    test -f ${generated}/bootc/generated/home-profile-catalog.json
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
  ciChecks = pkgs.runCommand "finite-ci-checks" {} ''
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
  exportTable = {
    architecture.package = architecture;
    ci-check.package = ciCheck;
    ci-checks.package = ciChecks;
    ci-prepare.package = applications.ciPrepare;
    ci-validate-plan.package = applications.validateCiPlan;
    ci-gate.package = applications.ciGate;
    ci-validate-image-shard.package = applications.validateImageShard;
    ci-image-reuse.package = applications.imageReuse;
    ci-image-verify.package = applications.imageVerify;
    ci-image-sign.package = applications.imageSign;
    ci-profile-stage.package = applications.profileStage;
    ci-rechunk-image.package = applications.rechunkImage;
    ci-image-build.package = applications.imageBuild;
    ci-image-sbom.package = applications.imageSbom;
    ci-sbom-attestation.package = applications.sbomAttestation;
    ci-promote-images.package = applications.promoteImages;
    ci-installer-build.package = applications.installerBuild;
    ci-installer-e2e.package = applications.installerE2e;
    ci-installer-smoke.package = applications.installerSmoke;
    ci-release-notes.package = applications.releaseNotes;
    ci-release-control.package = applications.releaseControl;
    ci-github-output.package = applications.githubOutput;
    ci-update-locks.package = applications.updateLocks;
    ci-home-release-update.package = applications.updateHomeRelease;
    ci-source-update.package = applications.sourceUpdate;
    ci-source-verify.package = applications.sourceVerify;
    ci-trusted-update.package = applications.trustedUpdate;
    ci-queue-dependabot.package = applications.queueDependabot;
    ci-package-cleanup.package = applications.packageCleanup;
    ci-repository-security-audit.package = applications.repositorySecurityAudit;
    ci-github-actions-secrets.package = applications.githubActionsSecrets;
    ci-load-bluefin.package = applications.loadBluefin;
    ci-lock-validate.package = applications.validateLocks;
    ci-cosign.package = pkgs.cosign;
    ci-oras.package = pkgs.oras;
    ci-skopeo.package = pkgs.skopeo;
    devenv = {
      package = outputDependencies.devenvPackage;
      appProgram = lib.getExe outputDependencies.devenvPackage;
    };
    default.package = generated;
    generated.package = generated;
    home-manager-template.package = homeScaffold;
    home-profile = {
      package = applications.homeProfile;
      appProgram = "${applications.homeProfile}/bin/finite-home-profile";
    };
    home-bootstrap = {
      package = applications.homeBootstrap;
      appProgram = "${applications.homeBootstrap}/bin/finite-home-bootstrap";
    };
    home-init = {
      package = applications.homeInit;
      appProgram = "${applications.homeInit}/bin/finite-home-init";
    };
    syft.package = pkgs.syft;
    cloud-init.appProgram = "${applications.cloudInit}/bin/finite-cloud-init";
    local-cache.appProgram = "${localCache}/bin/finite-local-cache";
    repository-security-audit.appProgram = lib.getExe applications.repositorySecurityAudit;
  };
  packageExports = lib.mapAttrs (_: export: export.package) (
    lib.filterAttrs (_: export: export ? package) exportTable
  );
  appExports = lib.mapAttrs (
    _: export: {
      type = "app";
      program = export.appProgram;
    }
  ) (lib.filterAttrs (_: export: export ? appProgram) exportTable);
in {
  flake = {
    lib.finite = {
      inherit home profiles;
      inherit cache catalog;
      profileOrder = profileSet.order;
    };
    flakeModules.home = homeFlakeModule;
    templates = {
      home-manager = {
        path = ../templates/home-manager;
        description = "Canonical self-contained Finite Home Manager configuration";
      };
      home-bluefin = {
        path = ../templates/home-manager;
        description = "Finite Home Manager template; bootstrap sets the Bluefin profile variables";
      };
      home-bluefin-dx = {
        path = ../templates/home-manager;
        description = "Finite Home Manager template; bootstrap sets the Bluefin DX profile variables";
      };
    };
    packages.${system} = packageExports;

    apps.${system} = appExports;

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
