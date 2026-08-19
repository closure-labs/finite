{
  bluefin,
  determinateNix,
  generated,
  imageBuilder,
  pkgs,
  version,
}: let
  mkRepositoryApp = {
    name,
    script,
    runtimeInputs,
  }: let
    scriptPath = ../. + "/${script}";
  in
    pkgs.writeShellApplication {
      inherit name runtimeInputs;
      text = ''
        repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
        [[ -f "''${repo_root}/flake.nix" ]] || {
          echo "Run this command from the Purplefin repository root" >&2
          exit 2
        }
        cd "''${repo_root}"
        exec ${pkgs.bash}/bin/bash ${scriptPath} "$@"
      '';
    };
in rec {
  classifyChanges = mkRepositoryApp {
    name = "purplefin-classify-changes";
    script = "automation/github/classify-changes.sh";
    runtimeInputs = [pkgs.coreutils];
  };

  githubActionsSecrets = mkRepositoryApp {
    name = "purplefin-github-actions-secrets";
    script = "automation/github/github-actions-secrets.sh";
    runtimeInputs = [pkgs.secretspec];
  };

  mkCi = checks: let
    checkNames = builtins.attrNames checks;
    checkPaths = map (name: builtins.unsafeDiscardStringContext (toString checks.${name})) checkNames;
    checkContract = builtins.toJSON {
      names = checkNames;
      paths = checkPaths;
    };
  in
    pkgs.writeShellApplication {
      name = "purplefin-ci";
      runtimeInputs = with pkgs; [cachix coreutils jq nix];
      text = ''
        export PURPLEFIN_CHECKS=${pkgs.lib.escapeShellArg checkContract}
        exec ${pkgs.bash}/bin/bash ${../automation/nix/ci.sh} "$@"
      '';
    };
  mkLocalCache = ciApplication:
    pkgs.writeShellApplication {
      name = "purplefin-local-cache";
      runtimeInputs = with pkgs; [coreutils secretspec];
      text = ''
        export PURPLEFIN_CI=${ciApplication}/bin/purplefin-ci
        exec ${pkgs.bash}/bin/bash ${../automation/nix/local-cache.sh} "$@"
      '';
    };
  verifyBluefin = pkgs.writeShellApplication {
    name = "purplefin-verify-bluefin";
    runtimeInputs = [pkgs.cosign];
    text = ''
      image='${bluefin.image}@${bluefin.digest}'
      cosign verify \
        --certificate-oidc-issuer '${bluefin.cosign.issuer}' \
        --certificate-identity '${bluefin.cosign.identity}' \
        "''${image}" >/dev/null
      printf '%s\n' "''${image}"
    '';
  };
  loadBluefin = pkgs.writeShellApplication {
    name = "purplefin-load-bluefin";
    runtimeInputs = with pkgs; [coreutils cosign skopeo];
    text = ''
      export PURPLEFIN_BLUEFIN_ARCHITECTURE=${bluefin.architecture}
      export PURPLEFIN_BLUEFIN_DIGEST=${bluefin.digest}
      export PURPLEFIN_BLUEFIN_IMAGE=${bluefin.image}
      export PURPLEFIN_BLUEFIN_TAG=${bluefin.tag}
      export PURPLEFIN_VERIFY_BLUEFIN=${verifyBluefin}/bin/purplefin-verify-bluefin
      exec ${pkgs.bash}/bin/bash ${../automation/sources/load-bluefin.sh} "$@"
    '';
  };
  sourceVerify = pkgs.writeShellApplication {
    name = "purplefin-source-verify";
    runtimeInputs = with pkgs; [cosign coreutils curl skopeo];
    text = ''
      export PURPLEFIN_BLUEFIN_ARCHITECTURE=${bluefin.architecture}
      export PURPLEFIN_BLUEFIN_DIGEST=${bluefin.digest}
      export PURPLEFIN_BLUEFIN_IMAGE=${bluefin.image}
      export PURPLEFIN_BLUEFIN_ISSUER=${bluefin.cosign.issuer}
      export PURPLEFIN_BLUEFIN_IDENTITY=${bluefin.cosign.identity}
      export PURPLEFIN_IMAGE_BUILDER_ARCHITECTURE=${imageBuilder.architecture}
      export PURPLEFIN_IMAGE_BUILDER_DIGEST=${imageBuilder.digest}
      export PURPLEFIN_IMAGE_BUILDER_IMAGE=${imageBuilder.image}
      export PURPLEFIN_DETERMINATE_NIX_INSTALLER_SHA256=${determinateNix.installer.sha256}
      export PURPLEFIN_DETERMINATE_NIX_INSTALLER_URL=${pkgs.lib.escapeShellArg determinateNix.installer.url}
      export PURPLEFIN_DETERMINATE_NIX_POLICY_SHA256=${determinateNix.selinuxPolicy.sha256}
      export PURPLEFIN_DETERMINATE_NIX_POLICY_URL=${pkgs.lib.escapeShellArg determinateNix.selinuxPolicy.url}
      export PURPLEFIN_DETERMINATE_NIX_VERSION=${determinateNix.version}
      exec ${pkgs.bash}/bin/bash ${../automation/sources/verify.sh} "$@"
    '';
  };
  sourceUpdate = mkRepositoryApp {
    name = "purplefin-source-update";
    script = "automation/sources/update.sh";
    runtimeInputs = with pkgs; [coreutils cosign curl diffutils gh jq nix skopeo];
  };
  releaseNotes = mkRepositoryApp {
    name = "purplefin-release-notes";
    script = "automation/release/notes.sh";
    runtimeInputs = with pkgs; [bash coreutils gawk gnugrep gnused];
  };
  trustedUpdate = mkRepositoryApp {
    name = "purplefin-trusted-update";
    script = "automation/github/validate-trusted-update.sh";
    runtimeInputs = with pkgs; [bash coreutils gh jq];
  };
  queueDependabot = mkRepositoryApp {
    name = "purplefin-queue-dependabot";
    script = "automation/github/queue-dependabot.sh";
    runtimeInputs = with pkgs; [bash gh jq];
  };
  packageCleanup = mkRepositoryApp {
    name = "purplefin-package-cleanup";
    script = "automation/github/package-cleanup.sh";
    runtimeInputs = with pkgs; [bash gh jq];
  };
  ciGate = import ./ci-applications/ci-gate.nix {inherit pkgs;};
  promoteImages = import ./ci-applications/promote-images.nix {inherit pkgs;};
  classifyCi = mkRepositoryApp {
    name = "purplefin-classify-ci";
    script = "automation/github/classify-ci.sh";
    runtimeInputs = with pkgs; [bash classifyChanges coreutils git];
  };
  imagePlan = import ./ci-applications/image-plan.nix {inherit pkgs;};
  shardPlan = import ./ci-applications/shard-plan.nix {inherit pkgs;};
  ciPlan = pkgs.writeShellApplication {
    name = "purplefin-ci-plan";
    runtimeInputs = [pkgs.jq];
    text = ''
      export PURPLEFIN_BASE_IMAGE=${bluefin.image}
      export PURPLEFIN_BASE_TAG=${bluefin.tag}
      export PURPLEFIN_BASE_DIGEST=${bluefin.digest}
      export PURPLEFIN_GENERATED_MATRIX=${generated}/bootc/generated/image-matrix.json
      export PURPLEFIN_IMAGE_PLAN=${imagePlan}/bin/purplefin-image-plan
      export PURPLEFIN_SHARD_PLAN=${shardPlan}/bin/purplefin-shard-plan
      export PURPLEFIN_VERIFY_BLUEFIN=${verifyBluefin}/bin/purplefin-verify-bluefin
      export PURPLEFIN_VERSION=${version}
      exec ${pkgs.bash}/bin/bash ${../automation/github/ci-plan.sh} "$@"
    '';
  };
  imageReuse = mkRepositoryApp {
    name = "purplefin-image-reuse";
    script = "bootc/builder/reuse-image.sh";
    runtimeInputs = with pkgs; [bash coreutils cosign jq skopeo];
  };
  validateImageShard = import ./ci-applications/validate-image-shard.nix {
    inherit bluefin generated loadBluefin pkgs version;
  };
  installerSmoke = mkRepositoryApp {
    name = "purplefin-installer-smoke";
    script = "tests/installer/smoke.sh";
    runtimeInputs = with pkgs; [bash coreutils gnugrep qemu_kvm];
  };
  installerBuild = import ./installer-application.nix {
    inherit generated imageBuilder installerSmoke pkgs;
  };
  sbomAttestation = mkRepositoryApp {
    name = "purplefin-sbom-attestation";
    script = "bootc/builder/sbom.sh";
    runtimeInputs = with pkgs; [coreutils gh jq];
  };
  imageSbom = mkRepositoryApp {
    name = "purplefin-image-sbom";
    script = "bootc/builder/sbom.sh";
    runtimeInputs = with pkgs; [coreutils gh jq nix syft];
  };
  imageBuild = pkgs.writeShellApplication {
    name = "purplefin-image-build";
    runtimeInputs = with pkgs; [bash coreutils jq podman];
    text = ''
      export PURPLEFIN_BASE_DIGEST=${bluefin.digest}
      export PURPLEFIN_GENERATED_ROOT=${generated}
      export PURPLEFIN_LOAD_BLUEFIN=${loadBluefin}/bin/purplefin-load-bluefin
      export PURPLEFIN_VERSION=${version}
      exec ${pkgs.bash}/bin/bash ${../automation/images/build.sh} "$@"
    '';
  };
  mkWorkflowToolset = {
    name,
    paths,
    required,
  }:
    assert builtins.all (application: builtins.elem application paths) required;
      pkgs.buildEnv {
        inherit name paths;
        ignoreCollisions = true;
      };

  workflowPrepare = mkWorkflowToolset {
    name = "purplefin-workflow-prepare";
    paths = with pkgs; [classifyCi ciPlan coreutils git jq];
    required = [classifyCi ciPlan];
  };
  workflowGate = mkWorkflowToolset {
    name = "purplefin-workflow-gate";
    paths = [ciGate];
    required = [ciGate];
  };
  workflowValidation = mkWorkflowToolset {
    name = "purplefin-workflow-validation";
    paths = [validateImageShard];
    required = [validateImageShard];
  };
  workflowPublish = mkWorkflowToolset {
    name = "purplefin-workflow-publish";
    paths = with pkgs; [coreutils cosign gh imageReuse jq loadBluefin nix promoteImages skopeo];
    required = [imageReuse loadBluefin promoteImages];
  };
  workflowSbom = mkWorkflowToolset {
    name = "purplefin-workflow-sbom";
    paths = with pkgs; [coreutils cosign gh imageSbom jq skopeo];
    required = [imageSbom];
  };
  workflowInstaller = mkWorkflowToolset {
    name = "purplefin-workflow-installer";
    paths = [installerBuild];
    required = [installerBuild];
  };
  workflowRelease = mkWorkflowToolset {
    name = "purplefin-workflow-release";
    paths = with pkgs; [coreutils cosign gh gzip jq nix oras releaseNotes sbomAttestation skopeo trustedUpdate];
    required = [releaseNotes sbomAttestation trustedUpdate];
  };
}
