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
    inherit lib;
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
  cache = let
    flakeConfig = (import ../flake.nix).nixConfig;
    url = builtins.head flakeConfig.extra-substituters;
  in {
    inherit url;
    name = lib.removeSuffix ".cachix.org" (lib.removePrefix "https://" url);
    publicKey = builtins.head flakeConfig.extra-trusted-public-keys;
  };
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
    inherit determinateNixInstaller determinateNixSelinuxFileContexts determinateNixSelinuxPolicy home lib pkgs profiles;
    profileOrder = profileSet.order;
    inherit version;
  };
  architecture = import ../lib/render-architecture.nix {
    inherit den lib pkgs;
    diagram = inputs.den-diagram.lib;
  };
  baseApplications = import ../lib/flake-applications.nix {
    devenv = inputs.devenv.packages.${system}.devenv;
    inherit bluefin bluefinDx bootcInstallerBundle dakotaInstallerLock dakotaIsoSource determinateNix generated pkgs version;
    cacheName = cache.name;
    secretspec = inputs.nixpkgs-weekly.legacyPackages.${system}.secretspec;
  };
  homeApplications = import ../lib/home-profile-applications.nix {inherit generated pkgs;};
  applications = baseApplications // homeApplications;
  homeFlakeModule = {
    imports = [
      inputs.den.flakeModule
      ../modules/sources/oci-locks.nix
      ../modules/aspects/base/default.nix
      ../modules/aspects/capabilities/devops/default.nix
      ../modules/aspects/roles/developer/default.nix
      ../modules/aspects/roles/executive/default.nix
      ../modules/aspects/roles/it/default.nix
      ../modules/aspects/roles/sales/default.nix
      ../modules/aspects/roles/support/default.nix
      ../modules/aspects/roles/trainer/default.nix
      ../modules/aspects/hardware/generic-x86_64/default.nix
      ../modules/aspects/hardware/dell-xps-9350-intel/default.nix
      (import ../lib/home-manager-flake-module.nix {
        finiteInputs = inputs;
        inherit (applications) homeBootstrap homeProfile;
      })
    ];
  };
  allRoles = ["developer" "sales" "trainer" "support" "executive" "it"];
  mkHomeProof = foundation: hardware: roles: let
    username = "finite-check-${foundation}-${hardware}-${lib.concatStringsSep "-" roles}";
    evaluated = lib.evalModules {
      specialArgs = {inherit inputs;};
      modules = [
        homeFlakeModule
        {
          finite.homeProfile = {
            schema = 1;
            inherit foundation hardware roles;
            identity = {
              inherit username;
              homeDirectory = "/var/home/${username}";
            };
          };
        }
      ];
    };
  in
    evaluated.config.flake.homeConfigurations.finite.activationPackage;
  foundationProofs = lib.concatMap (
    foundation:
      lib.concatMap (hardware: [
        (mkHomeProof foundation hardware [])
        (mkHomeProof foundation hardware allRoles)
      ]) ["generic-x86_64" "dell-xps-9350-intel"]
  ) ["bluefin" "bluefin-dx"];
  roleProofs = lib.concatMap (
    foundation:
      map (role: mkHomeProof foundation "generic-x86_64" [role]) allRoles
  ) ["bluefin" "bluefin-dx"];
  homeProofsEvaluated =
    builtins.deepSeq (
      map (activation: activation.drvPath) (foundationProofs ++ roleProofs)
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
    src = inputs.self;
    filter = path: _type: let
      relative = lib.removePrefix "${toString inputs.self}/" (toString path);
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
in {
  flake = {
    lib.finite = {
      inherit home profiles;
      inherit cache;
      profileOrder = profileSet.order;
    };
    flakeModules.home = homeFlakeModule;
    templates = {
      home-bluefin = {
        path = ../templates/home-bluefin;
        description = "Finite Bluefin standalone Home Manager foundation";
      };
      home-bluefin-dx = {
        path = ../templates/home-bluefin-dx;
        description = "Finite Bluefin DX standalone Home Manager foundation";
      };
    };
    packages.${system} = {
      inherit architecture;
      ci-check = ciCheck;
      ci-checks = ciChecks;
      ci-prepare = applications.ciPrepare;
      ci-validate-plan = applications.validateCiPlan;
      ci-gate = applications.ciGate;
      ci-validate-image-shard = applications.validateImageShard;
      ci-image-reuse = applications.imageReuse;
      ci-image-sign = applications.imageSign;
      ci-rechunk-image = applications.rechunkImage;
      ci-image-build = applications.imageBuild;
      ci-image-sbom = applications.imageSbom;
      ci-sbom-attestation = applications.sbomAttestation;
      ci-promote-images = applications.promoteImages;
      ci-installer-build = applications.installerBuild;
      ci-installer-e2e = applications.installerE2e;
      ci-installer-smoke = applications.installerSmoke;
      ci-release-notes = applications.releaseNotes;
      ci-update-locks = applications.updateLocks;
      ci-home-release-update = applications.updateHomeRelease;
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
      home-profile = applications.homeProfile;
      home-bootstrap = applications.homeBootstrap;
      inherit (pkgs) syft;
    };

    apps.${system} = {
      devenv = {
        type = "app";
        program = lib.getExe inputs.devenv.packages.${system}.devenv;
      };
      home-profile = {
        type = "app";
        program = "${applications.homeProfile}/bin/finite-home-profile";
      };
      home-bootstrap = {
        type = "app";
        program = "${applications.homeBootstrap}/bin/finite-home-bootstrap";
      };
      cloud-init = {
        type = "app";
        program = "${applications.cloudInit}/bin/finite-cloud-init";
      };
      local-cache = {
        type = "app";
        program = "${localCache}/bin/finite-local-cache";
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
