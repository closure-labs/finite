{
  bluefin,
  bluefinDx,
  bootcInstallerBundle,
  cacheName,
  dakotaInstallerLock,
  dakotaIsoSource,
  devenv,
  determinateNix,
  generated,
  pkgs,
  secretspec,
  version,
}: let
  scope = {
    inherit
      bluefin
      bluefinDx
      bootcInstallerBundle
      cacheName
      dakotaInstallerLock
      dakotaIsoSource
      devenv
      determinateNix
      generated
      pkgs
      secretspec
      version
      ;
  };
  callPackage = pkgs.lib.callPackageWith scope;
  repositoryApplications =
    callPackage ./ci-applications/repository-operations.nix {};
  sourceApplications =
    callPackage ./ci-applications/source-operations.nix {};
  releaseApplications =
    callPackage ./ci-applications/release-operations.nix {};
  sbomApplications =
    callPackage ./ci-applications/sbom-operations.nix {};
  imageApplications =
    pkgs.lib.callPackageWith (scope // sourceApplications)
    ./ci-applications/image-operations.nix
    {};

  coreApplications = rec {
    classifyChanges = import ./ci-applications/classify-changes.nix {inherit pkgs;};
    updateLocks = import ./ci-applications/update-locks.nix {
      inherit devenv pkgs;
    };
    updateHomeRelease = import ./ci-applications/update-home-release.nix {inherit pkgs;};
    repositorySecurityAudit = import ./ci-applications/repository-security-audit.nix {
      inherit pkgs;
      policy = ../automation/github/repository-security.json;
    };

    validateCiPlan = import ./ci-applications/validate-ci-plan.nix {inherit pkgs;};
    ciGate = import ./ci-applications/ci-gate.nix {inherit pkgs validateCiPlan;};
    promoteImages = import ./ci-applications/promote-images.nix {inherit pkgs;};
    classifyCi = import ./ci-applications/classify-ci.nix {
      inherit classifyChanges pkgs;
    };
    imagePlan = import ./ci-applications/image-plan.nix {inherit pkgs;};
    shardPlan = import ./ci-applications/shard-plan.nix {inherit pkgs;};
    validateLocks = import ./ci-applications/validate-locks.nix {inherit pkgs;};
    buildCiPlan = import ./ci-applications/build-ci-plan.nix {
      inherit bluefin generated imagePlan pkgs shardPlan version;
      inherit (sourceApplications) verifyBluefin;
    };
    ciPrepare = import ./ci-applications/ci-prepare.nix {
      inherit buildCiPlan classifyCi pkgs validateCiPlan;
    };

    imageSign = import ./ci-applications/image-sign.nix {inherit pkgs;};
    rechunkImage = import ./ci-applications/rechunk-image.nix {inherit pkgs;};
    validateImageShard = import ./ci-applications/validate-image-shard.nix {
      inherit generated pkgs rechunkImage version;
      inherit (sourceApplications) loadBluefin;
    };

    installerE2e = import ./ci-applications/installer-e2e.nix {inherit pkgs;};
    installerSmoke = import ./ci-applications/installer-smoke.nix {inherit pkgs;};
    installerBuild = import ./installer-application.nix {
      inherit
        bootcInstallerBundle
        dakotaInstallerLock
        dakotaIsoSource
        generated
        pkgs
        ;
    };
  };

  githubOutput = callPackage ./ci-applications/github-output.nix {};
  imageVerify = callPackage ./ci-applications/image-verify.nix {};
  workflowScope =
    scope
    // sourceApplications
    // imageApplications
    // sbomApplications
    // coreApplications
    // {
      inherit githubOutput imageVerify;
    };
  workflowCallPackage = pkgs.lib.callPackageWith workflowScope;
  workflowApplications = {
    inherit githubOutput imageVerify;
    profileStage = workflowCallPackage ./ci-applications/profile-stage.nix {};
    releaseControl = workflowCallPackage ./ci-applications/release-control.nix {};
  };
in
  repositoryApplications
  // sourceApplications
  // releaseApplications
  // sbomApplications
  // imageApplications
  // coreApplications
  // workflowApplications
