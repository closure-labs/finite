{
  applications,
  architecture,
  generated,
  lib,
  pkgs,
}: let
  root = ../.;
  inherit (lib) fileset;
  localState = fileset.unions [
    (fileset.maybeMissing ../.devenv)
    (fileset.maybeMissing ../.direnv)
  ];
  projectFiles = fileset.difference root localState;
  sourceFor = selected:
    fileset.toSource {
      inherit root;
      fileset = fileset.unions selected;
    };
  shellFiles = fileset.intersection projectFiles (
    fileset.fileFilter (file: file.type == "regular" && lib.hasSuffix ".sh" file.name) root
  );
  nixFiles = fileset.intersection projectFiles (
    fileset.fileFilter (file: file.type == "regular" && lib.hasSuffix ".nix" file.name) root
  );
  textFiles = fileset.intersection projectFiles (
    fileset.fileFilter (
      file:
        file.type
        == "regular"
        && (
          builtins.elem file.name [".editorconfig" ".gitignore" "Containerfile" "Containerfile.derived" "Justfile" "LICENSE" "VERSION"]
          || builtins.any (suffix: lib.hasSuffix suffix file.name) [
            ".conf"
            ".css"
            ".json"
            ".md"
            ".nix"
            ".sh"
            ".toml"
            ".xml"
            ".yaml"
            ".yml"
            ".zsh"
          ]
        )
    )
    root
  );
  shellSource = sourceFor [shellFiles];
  nixSource = sourceFor [nixFiles];
  repositorySource = sourceFor [
    ../.github/workflows/build-installer.yml
    ../.github/workflows/build.yml
    ../flake.nix
    ../VERSION
    ../bootc/Containerfile
    ../bootc/Containerfile.derived
    ../bootc/builder
    ../lib/domain-catalog.nix
    ../lib/home-manager-flake-module.nix
    ../lib/home-profile-applications.nix
    ../lib/mk-pkgs.nix
    ../lib/project-policy.nix
    ../modules/aspects
    ../modules/outputs.nix
    ../sources
    ../secretspec.toml
    ../tests/repository/contracts.sh
    ../tests/home
    ../templates
  ];
  homeSource = sourceFor [
    ../lib/domain-catalog.nix
    ../lib/home-manager-flake-module.nix
    ../lib/home-profile-applications.nix
    ../modules/aspects/base/rootfs/usr/libexec/finite/home-first-login
    ../templates
    ../tests/home
  ];
  documentationSource = sourceFor [textFiles];
  automationSource = sourceFor [
    ../automation/github/repository-security.json
    ../docs/ci-and-releases.md
    ../docs/configuration.md
    ../docs/installation.md
    ../flake.lock
    ../flake.nix
    ../lib/ci-applications/validate-locks.nix
    ../modules/outputs.nix
    ../tests/automation
    ../tests/fixtures/repository-security
    ../tests/fixtures/ci-applications
    ../tests/repository/contracts.sh
  ];
  bootcSource = sourceFor [
    ../.github/syft.yaml
    ../bootc/builder
    ../flake.nix
    ../modules/aspects
    ../tests/bootc
  ];
  installerSource = sourceFor [
    ../.github/actions/build-installer
    ../.github/actions/save-installer-seed
    ../flake.nix
    ../installer
    ../lib/ci-applications/installer-e2e.nix
    ../lib/ci-applications/installer-smoke.nix
    ../lib/installer-application.nix
    ../modules/aspects/base/rootfs/usr/lib/bootc/install/00-defaults.toml
    ../sources/dakota-installer.json
    ../tests/installer
  ];
  aspectsSource = sourceFor [
    ../modules/aspects
  ];
  releaseSource = sourceFor [
    ../CHANGELOG.md
    ../VERSION
    ../flake.nix
  ];
  upstreamSource = sourceFor [
    ../bootc/Containerfile
    ../devenv.nix
    ../devenv.yaml
    ../flake.nix
    ../lib/ci-applications/image-operations.nix
    ../lib/ci-applications/repository-operations.nix
    ../lib/ci-applications/source-operations.nix
    ../lib/project-policy.nix
    ../lib/flake-applications.nix
    ../modules/outputs.nix
    ../modules/profiles/definitions.nix
    ../sources
    ../secretspec.toml
  ];
  workflowSource = sourceFor [
    ../.github
    ../README.md
    ../devenv-tasks.nix
    ../devenv.nix
    ../devenv.yaml
    ../docs
    ../lib/ci-applications
    ../lib/domain-catalog.nix
    ../lib/flake-applications.nix
    ../lib/project-policy.nix
    ../automation/github/policies
    ../automation/github/repository-security.json
    ../bootc/Containerfile
    ../flake.nix
    ../lib/installer-application.nix
    ../modules/aspects/base/rootfs/usr/lib/bootc/install/00-defaults.toml
    ../modules/outputs.nix
    ../installer/live
    ../installer/prepare-dakota-iso-source
    ../tests/installer
    ../tests/repository
  ];
  mkSourceCheck = {
    commands,
    generatedRoot ? null,
    name,
    source,
    tools ? [],
  }:
    pkgs.runCommand "finite-${name}" {
      nativeBuildInputs = [pkgs.bash pkgs.coreutils] ++ tools;
    } ''
      export HOME="$TMPDIR/home"
      mkdir -p "$HOME" source
      cp -R ${source}/. source/
      chmod -R u+w source
      cd source
      ${lib.optionalString (generatedRoot != null) ''
        export FINITE_GENERATED_ROOT=${generatedRoot}
      ''}
      export FINITE_HERMETIC_CHECK=true
      export FINITE_SOURCE_ROOT="$PWD"
      ${commands}
      touch "$out"
    '';
  workflowApplicationNames = [
    "ciPrepare"
    "validateCiPlan"
    "validateImageShard"
    "imageReuse"
    "imageVerify"
    "imageSign"
    "profileStage"
    "rechunkImage"
    "loadBluefin"
    "promoteImages"
    "installerBuild"
    "installerE2e"
    "imageSbom"
    "releaseNotes"
    "releaseControl"
    "githubOutput"
    "updateLocks"
    "updateHomeRelease"
    "sbomAttestation"
    "trustedUpdate"
    "ciGate"
  ];
  # lib.getExe checks each application's executable contract during Flake
  # evaluation without making the workflow source check realize every runtime
  # closure merely to run `test -x` on its store path.
  workflowApplicationsEvaluated =
    builtins.deepSeq (
      map (name: lib.getExe applications.${name}) workflowApplicationNames
    )
    true;
in {
  shell = mkSourceCheck {
    name = "shell-checks";
    source = shellSource;
    tools = with pkgs; [findutils gnugrep shellcheck];
    commands = ''
      set -euo pipefail

      mapfile -d $'\0' shell_files < <(
        find . -type f -name '*.sh' -print0
      )
      bash -n "''${shell_files[@]}"
      # Dynamic container build roots cannot be followed statically. Every sourced
      # shell file is already present in this complete input array.
      shellcheck --exclude=SC1091 --external-sources --source-path=SCRIPTDIR \
        "''${shell_files[@]}"

      test ! -e bootc/builder/reuse-image.sh
      test ! -e bootc/builder/sbom.sh
      while IFS= read -r shell_file; do
        case "''${shell_file}" in
          ./bootc/builder/derived.sh | ./bootc/builder/full.sh | ./bootc/builder/lib/*.sh | \
          ./installer/**/*.sh | \
          ./modules/aspects/*.sh | ./modules/aspects/**/*.sh | ./tests/*.sh | ./tests/**/*.sh)
            ;;
          *)
            echo "Shell file has no container, runtime, or focused-test ownership: ''${shell_file}" >&2
            exit 1
            ;;
        esac
      done < <(printf '%s\n' "''${shell_files[@]}" | LC_ALL=C sort)
    '';
  };

  repository = mkSourceCheck {
    name = "repository-contracts";
    source = repositorySource;
    generatedRoot = generated;
    tools = with pkgs; [findutils gnugrep jq ripgrep];
    commands = ''
      bash tests/repository/contracts.sh
      grep -qF 'features_roles_developer' ${architecture}/namespace.mmd
      grep -qF 'features_roles_support' ${architecture}/namespace.mmd
      grep -qF 'operations_github_build --> operations_checks_all' ${architecture}/namespace.mmd
      grep -qF 'operations_checks_all --> operations_checks_repository_contracts' ${architecture}/namespace.mmd
      grep -qF 'operations_checks_all --> operations_checks_bootc_engine' ${architecture}/namespace.mmd
      grep -qF 'operations_github_build --> operations_delivery_installer' ${architecture}/namespace.mmd
      grep -qF 'operations_updates_bluefin --> sources_bluefin' ${architecture}/namespace.mmd
      grep -qF 'operations_updates_bluefin --> sources_bluefin_dx' ${architecture}/namespace.mmd
      grep -qF 'operations_github_bluefin_update --> operations_updates_bluefin' ${architecture}/namespace.mmd
      grep -qF 'operations_updates_determinate_nix --> sources_determinate_nix' ${architecture}/namespace.mmd
      grep -qF 'operations_github_determinate_nix_update --> operations_updates_determinate_nix' \
        ${architecture}/namespace.mmd
      grep -qF 'operations_delivery_installer --> operations_delivery_images' ${architecture}/namespace.mmd
    '';
  };

  home = mkSourceCheck {
    name = "home-profile-contracts";
    source = homeSource;
    generatedRoot = generated;
    tools = with pkgs; [getent jq yq-go];
    commands = ''
      set -euo pipefail
      bash tests/home/contracts.sh \
        ${applications.homeProfile}/bin/finite-home-profile \
        ${applications.homeBootstrap}/bin/finite-home-bootstrap \
        ${applications.cloudInit}/bin/finite-cloud-init
    '';
  };

  upstream = mkSourceCheck {
    name = "upstream-contracts";
    source = upstreamSource;
    tools = with pkgs; [gnugrep jq ripgrep yq-go];
    commands = ''
      # shellcheck disable=SC2016,SC2251
      set -euo pipefail

      jq -e '
        .schema == 1 and
        .image == "ghcr.io/ublue-os/bluefin" and
        .tag == "stable" and
        .architecture == "amd64" and
        (.digest | test("^sha256:[0-9a-f]{64}$")) and
        (.cosign.issuer | startswith("https://")) and
        (.cosign.identity | startswith("https://"))
      ' sources/bluefin.json >/dev/null
      jq -e '
        .schema == 1 and
        .image == "ghcr.io/ublue-os/bluefin-dx" and
        .tag == "stable" and
        .architecture == "amd64" and
        (.digest | test("^sha256:[0-9a-f]{64}$")) and
        (.cosign.issuer | startswith("https://")) and
        (.cosign.identity | startswith("https://"))
      ' sources/bluefin-dx.json >/dev/null
      jq -e '
        .schema == 3 and
        .iso_source.owner == "projectbluefin" and
        .iso_source.repository == "dakota-iso" and
        (.iso_source.revision | test("^[0-9a-f]{40}$")) and
        (.iso_source.hash | startswith("sha256-")) and
        (.installer.url | startswith("https://github.com/projectbluefin/bootc-installer/releases/download/")) and
        (.installer.sha256 | test("^[0-9a-f]{64}$")) and
        .live_image.image == "ghcr.io/projectbluefin/dakota" and
        .live_image.tag == "stable" and
        .live_image.architecture == "amd64" and
        (.live_image.digest | test("^sha256:[0-9a-f]{64}$")) and
        .live_image.cosign.issuer == "https://token.actions.githubusercontent.com" and
        (.live_image.cosign.identity | contains("projectbluefin/dakota/.github/workflows/publish.yml")) and
        .builder.image == "docker.io/library/debian" and
        .builder.tag == "bookworm" and
        .builder.architecture == "amd64" and
        (.builder.digest | test("^sha256:[0-9a-f]{64}$"))
      ' sources/dakota-installer.json >/dev/null
      jq -e '
        .schema == 1 and
        .architecture == "x86_64-linux" and
        (.version | test("^[0-9]+\\.[0-9]+\\.[0-9]+$")) and
        (.minimumRuntimeVersion | test("^[0-9]+\\.[0-9]+\\.[0-9]+$")) and
        (.installer.url | startswith("https://github.com/DeterminateSystems/nix-installer/releases/download/")) and
        (.installer.sha256 | test("^[0-9a-f]{64}$")) and
        (.selinuxPolicy.url | startswith("https://raw.githubusercontent.com/DeterminateSystems/nix-installer/")) and
        (.selinuxPolicy.sha256 | test("^[0-9a-f]{64}$")) and
        (.selinuxFileContexts.url | endswith("/nix.fc")) and
        (.selinuxFileContexts.sha256 | test("^[0-9a-f]{64}$"))
      ' sources/determinate-nix.json >/dev/null
      yq -p toml -o json '.' secretspec.toml |
        jq -e '
          .project.name == "finite" and
          .providers["github-actions"] == "env" and
          .profiles["local-cache"].CACHIX_AUTH_TOKEN.required == true and
          (.profiles["github-actions"] | keys) == ["CACHIX_AUTH_TOKEN", "MERGE_QUEUE_TOKEN"] and
          all(.profiles["github-actions"][]; .required == false) and
          .scopes.cachix.secrets == ["CACHIX_AUTH_TOKEN"] and
          .scopes["github-actions"].secrets == ["CACHIX_AUTH_TOKEN", "MERGE_QUEUE_TOKEN"]
        ' >/dev/null
      grep -qF 'github-actions = "env"' secretspec.toml
      grep -qF 'ref = { item = "GITHUB_ACTIONS_CACHIX_AUTH_TOKEN" }' secretspec.toml
      grep -qF 'ref = { item = "GITHUB_ACTIONS_MERGE_QUEUE_TOKEN" }' secretspec.toml
      ! rg -qF 'cachix watch-exec' lib/ci-applications lib/flake-applications.nix
      grep -qF 'cachix push --omit-deriver ''${pkgs.lib.escapeShellArg' \
        lib/ci-applications/repository-operations.nix
      ! rg -qF 'unsafeDiscardStringContext' lib/ci-applications lib/flake-applications.nix
      ! grep -qF 'nix --accept-flake-config eval --json' \
        lib/ci-applications/repository-operations.nix
      ! rg -qF 'quotedPaths' lib/ci-applications lib/flake-applications.nix
      grep -qF 'flake_uri="git+file://' lib/ci-applications/repository-operations.nix
      grep -qF '?shallow=1"' lib/ci-applications/repository-operations.nix
      grep -qF -- '--no-build' lib/ci-applications/repository-operations.nix
      grep -qF 'nix --accept-flake-config build' lib/ci-applications/repository-operations.nix
      grep -qF -- '--no-link' lib/ci-applications/repository-operations.nix
      grep -qF -- '--print-out-paths' lib/ci-applications/repository-operations.nix
      grep -qF 'readlink -f' lib/ci-applications/repository-operations.nix
      [[ "$(grep -cF 'nix path-info --json' \
        lib/ci-applications/repository-operations.nix)" == 1 ]]
      [[ "$(grep -m1 -nF 'nix --accept-flake-config build' \
        lib/ci-applications/repository-operations.nix | cut -d: -f1)" -lt \
        "$(grep -m1 -nF 'nix --accept-flake-config flake check' \
        lib/ci-applications/repository-operations.nix | cut -d: -f1)" ]]
      grep -qF 'ci-checks.package = ciChecks' modules/outputs.nix
      grep -qF 'ln -s' modules/outputs.nix
      grep -qF 'max_closure_size=$((1024 * 1024))' \
        lib/ci-applications/repository-operations.nix
      ! grep -qF 'dockerTools.pullImage' modules/outputs.nix
      ! grep -qF 'bluefin-upstream' modules/outputs.nix
      grep -qF 'skopeo copy' lib/ci-applications/source-operations.nix
      grep -qF 'containers-storage:' lib/ci-applications/source-operations.nix
      grep -qF 'host_podman' lib/ci-applications/source-operations.nix
      grep -qF 'unshare "$0"' lib/ci-applications/source-operations.nix
      grep -qF -- '--label "io.finite.build.profile=' \
        lib/ci-applications/image-operations.nix
      old_product=purple
      old_product+=fin
      ! rg -i "''${old_product}" --hidden -g '!.git/**'
      grep -qF 'https://finite-os.cachix.org' flake.nix
      grep -qF 'finite-os.cachix.org-1:iwOc148wD1hSWnyNwhP3DsMxBv8WcL+ppMwcRIvx4Ko=' flake.nix
      grep -qF 'https://cachix.cachix.org' flake.nix
      grep -qF 'cachix.cachix.org-1:eWNHQldwUO7G2VkjpnjDbWwy4KQ/HNxht7H4SSoMckM=' flake.nix
      grep -qF 'https://finite-os.cachix.org' lib/project-policy.nix
      grep -qF 'finite-os.cachix.org-1:iwOc148wD1hSWnyNwhP3DsMxBv8WcL+ppMwcRIvx4Ko=' \
        lib/project-policy.nix
      grep -qF 'https://cachix.cachix.org' lib/project-policy.nix
      grep -qF 'cachix.cachix.org-1:eWNHQldwUO7G2VkjpnjDbWwy4KQ/HNxht7H4SSoMckM=' \
        lib/project-policy.nix
      grep -qF 'cacheName' devenv.nix
      grep -qF 'provider: local' devenv.yaml
      grep -qF 'local = "file:~/.other-fun-things"' secretspec.toml
      grep -qF '.cachix-auth-finite' secretspec.toml
      ! rg -qF 'token_file=' lib/ci-applications lib/flake-applications.nix
      grep -qF 'runtimeInputs = [devenv secretspec];' \
        lib/ci-applications/repository-operations.nix
      grep -qF '#ci-checks.drvPath' lib/ci-applications/repository-operations.nix
      grep -qF 'ci_checks_drv}^*' lib/ci-applications/repository-operations.nix
      grep -qFx 'ARG BASE_REF' bootc/Containerfile
      ! grep -qF 'bluefin:stable' bootc/Containerfile
    '';
  };

  documentation = mkSourceCheck {
    name = "documentation-checks";
    source = documentationSource;
    tools = with pkgs; [file findutils gawk gnugrep ripgrep];
    commands = ''
      set -euo pipefail

      bash tests/repository/text-style.sh
      bash tests/repository/markdown-links.sh
    '';
  };

  automation = mkSourceCheck {
    name = "automation-checks";
    source = automationSource;
    tools = with pkgs; [
      applications.classifyChanges
      applications.classifyCi
      applications.buildCiPlan
      applications.ciPrepare
      applications.validateCiPlan
      applications.ciGate
      applications.githubOutput
      applications.imageVerify
      applications.profileStage
      applications.promoteImages
      applications.releaseControl
      applications.repositorySecurityAudit
      applications.trustedUpdate
      applications.updateHomeRelease
      git
      gnugrep
      jq
    ];
    commands = ''
      set -euo pipefail
      bash tests/automation/classify-changes.sh
      bash tests/automation/classify-ci.sh
      bash tests/automation/ci-gate.sh
      bash tests/automation/ci-applications.sh \
        ${applications.githubOutput}/bin/finite-github-output \
        ${applications.imageVerify}/bin/finite-image-verify \
        ${applications.profileStage}/bin/finite-profile-stage \
        ${applications.releaseControl}/bin/finite-release-control \
        tests/fixtures/ci-applications
      bash tests/automation/promote-images.sh
      bash tests/automation/repository-security.sh \
        ${applications.repositorySecurityAudit}/bin/finite-repository-security-audit \
        automation/github/repository-security.json \
        tests/fixtures/repository-security
      bash tests/automation/trusted-update.sh
      bash tests/automation/update-home-release.sh
    '';
  };

  bootc = mkSourceCheck {
    name = "bootc-checks";
    source = bootcSource;
    generatedRoot = generated;
    tools = with pkgs; [
      applications.imagePlan
      applications.imageReuse
      applications.imageSign
      applications.imageSbom
      applications.rechunkImage
      applications.shardPlan
      applications.validateImageShard
      diffutils
      findutils
      gnugrep
      jq
    ];
    commands = ''
      set -euo pipefail

      bash tests/bootc/derived-profile.sh
      bash tests/bootc/plan.sh
      bash tests/bootc/rechunk.sh \
        ${applications.rechunkImage}/bin/finite-rechunk-image
      bash tests/bootc/reuse-image.sh
      bash tests/bootc/sign-image.sh
      bash tests/bootc/sbom.sh
      bash tests/bootc/shards.sh
    '';
  };

  installer = mkSourceCheck {
    name = "installer-contracts";
    source = installerSource;
    tools = [
      applications.installerE2e
      pkgs.gnugrep
      pkgs.gnused
      pkgs.jq
      pkgs.util-linux
    ];
    commands = ''
      set -euo pipefail

      bash tests/installer/contracts.sh \
        ${applications.installerBuild}/bin/finite-installer-build
      bash tests/installer/smoke.sh \
        ${applications.installerSmoke}/bin/finite-installer-smoke
    '';
  };

  aspects = mkSourceCheck {
    name = "aspect-contracts";
    source = aspectsSource;
    tools = with pkgs; [gnugrep systemd util-linux];
    commands = ''
      set -euo pipefail

      bash modules/aspects/base/tests/contracts.sh
      bash modules/aspects/base/tests/determinate-version.sh
      bash modules/aspects/base/tests/nix-lifecycle.sh
      bash modules/aspects/base/tests/nix-systemd.sh
      bash modules/aspects/capabilities/devops/tests/contracts.sh
      bash modules/aspects/roles/support/tests/contracts.sh
      bash modules/aspects/hardware/dell-xps-9350-intel/tests/lid-auth.sh
      bash modules/aspects/hardware/dell-xps-9350-intel/tests/policies.sh
    '';
  };

  release = mkSourceCheck {
    name = "release-contracts";
    source = releaseSource;
    tools = with pkgs; [applications.releaseNotes gawk gnugrep gnused];
    commands = ''
      set -euo pipefail

      latest_changelog_version="$({
        sed -nE 's/^## \[([0-9]+\.[0-9]+\.[0-9]+)\] - [0-9]{4}-[0-9]{2}-[0-9]{2}$/\1/p' \
          CHANGELOG.md | head -n 1
      })"
      test -n "''${latest_changelog_version}"
      release_notes="$(finite-release-notes "''${latest_changelog_version}" CHANGELOG.md)"
      for heading in Added Changed Fixed Security; do
        grep -qF "### ''${heading}" <<<"''${release_notes}"
      done
      if grep -qF '[Unreleased]:' <<<"''${release_notes}"; then
        echo 'release notes unexpectedly contain the Unreleased link target' >&2
        exit 1
      fi
      if [[ "$(<VERSION)" != *-dev.* ]]; then
        [[ "$(<VERSION)" == "''${latest_changelog_version}" ]]
      fi
    '';
  };

  workflows = mkSourceCheck {
    name = "workflow-checks";
    source = assert workflowApplicationsEvaluated; workflowSource;
    tools = with pkgs; [actionlint findutils gnugrep jq yq-go zizmor];
    commands = ''
      # shellcheck disable=SC2016,SC2251
      set -euo pipefail

      jq -e '
        .target == "branch" and
        .enforcement == "active" and
        any(.rules[]; .type == "merge_queue") and
        any(.rules[]; .type == "required_status_checks" and
          any(.parameters.required_status_checks[];
            .context == "CI gate" and .integration_id == 15368))
      ' automation/github/policies/main-merge-queue.json >/dev/null
      jq -e '
        .target == "branch" and
        .enforcement == "active" and
        all(.rules[]; .type != "merge_queue") and
        any(.rules[]; .type == "required_status_checks" and
          .parameters.strict_required_status_checks_policy == true and
          any(.parameters.required_status_checks[];
            .context == "CI gate" and .integration_id == 15368))
      ' automation/github/policies/main-protection.json >/dev/null
      jq -e '
        .schema == 1 and
        .repository == "closure-labs/finite" and
        .actions.allowed_actions == "selected" and
        .actions.sha_pinning_required == true and
        .actions.selected_actions.github_owned_allowed == true and
        .actions.selected_actions.verified_allowed == false and
        (.actions.selected_actions.patterns_allowed | sort) == [
          "DeterminateSystems/determinate-nix-action@*",
          "DeterminateSystems/nix-installer-action@*",
          "peter-evans/create-pull-request@*"
        ] and
        .actions.workflow_permissions.default_workflow_permissions == "read" and
        .actions.workflow_permissions.can_approve_pull_request_reviews == false and
        all(.security[]; . == true) and
        (.environments | keys | sort) == ["package-cleanup", "release"] and
        all(.environments[];
          .can_admins_bypass == false and
          .prevent_self_review == false and
          .required_reviewers == ["declarative-dale"] and
          .deployment_branch_policy.branches == ["main"])
      ' automation/github/repository-security.json >/dev/null

      grep -qF 'nix shell --accept-flake-config .#ci-check' .github/workflows/build.yml
      grep -qF 'nix shell --accept-flake-config .#ci-prepare' .github/workflows/build.yml
      for updater in \
        update-bluefin.yml \
        update-determinate-nix.yml \
        update-flake-lock.yml \
        update-home-release.yml; do
        grep -qF '.#ci-trusted-update' ".github/workflows/''${updater}"
      done
      yq -e '
        [(.jobs.prepare.steps + .jobs.release.steps)[] |
          select(.run != null and (.run | contains("finite-trusted-update")))] |
        length | select(. == 2)
      ' .github/workflows/release.yml >/dev/null
      yq -e '
        [(.jobs.prepare.steps + .jobs.release.steps)[] |
          select(.uses == "peter-evans/create-pull-request@5f6978faf089d4d20b00c7766989d076bb2fc7f1")] |
        length | select(. == 2)
      ' .github/workflows/release.yml >/dev/null
      yq -e '
        [(.jobs.prepare.steps + .jobs.release.steps)[] |
          select(.run != null and (.run | contains("finite-release-control")))] |
        length | select(. == 8)
      ' .github/workflows/release.yml >/dev/null
      yq -e '
        [(.jobs.prepare.steps + .jobs.release.steps)[] |
          select(.run != null and (.run | contains("finite-github-output")))] |
        length | select(. == 5)
      ' .github/workflows/release.yml >/dev/null
      yq -e '.jobs.prepare["timeout-minutes"] | select(. == 240)' \
        .github/workflows/release.yml >/dev/null
      yq -e '.jobs.release["timeout-minutes"] | select(. == 240)' \
        .github/workflows/release.yml >/dev/null
      yq -e '
        .jobs.prepare.steps[] |
        select(.name == "Checkout release source") |
        .with["fetch-depth"] | select(. == 0)
      ' .github/workflows/release.yml >/dev/null
      yq -e '
        .jobs.release.steps[] |
        select(.name == "Checkout release source") |
        .with["fetch-depth"] | select(. == 1)
      ' .github/workflows/release.yml >/dev/null
      yq -e '
        .jobs.prepare.steps[] |
        select(.name == "Reuse or dispatch the release-candidate build") |
        .env.SOURCE_SHA | select(contains("steps.source.outputs.source_sha"))
      ' .github/workflows/release.yml >/dev/null
      ! grep -qF 'steps.version.outputs.source_sha' .github/workflows/release.yml
      ! grep -qF 'git push origin HEAD:main' .github/workflows/release.yml
      ! grep -R -qF 'github-actions[bot]' .github/workflows
      grep -qF 'cron: "7 7,19 * * *"' .github/workflows/update-bluefin.yml
      grep -qF 'finite-source-update bluefin ' .github/workflows/update-bluefin.yml
      grep -qF 'finite-source-update bluefin-dx ' .github/workflows/update-bluefin.yml
      grep -qF 'finite-source-update determinate-nix ' .github/workflows/update-determinate-nix.yml
      grep -qF 'finite-update-locks ' .github/workflows/update-flake-lock.yml
      grep -qF 'finite-update-home-release ' .github/workflows/update-home-release.yml
      yq -e '
        .jobs.build.steps[] |
        select(.name == "Stage immutable profile image") |
        .run | select(contains("finite-profile-stage"))
      ' .github/workflows/build-profile.yml >/dev/null
      yq -e '
        [.jobs.build.steps[] |
          select(.run != null and (.run | contains("finite-image-verify")))] |
        length | select(. == 2)
      ' .github/workflows/build-profile.yml >/dev/null
      yq -e '
        [.jobs.build.steps[] |
          select(.uses == "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6")] |
        length | select(. == 2)
      ' .github/workflows/build-profile.yml >/dev/null
      grep -qF 'finite-ci-prepare' .github/workflows/build.yml
      grep -qF 'finite-validate-image-shard' .github/workflows/build.yml
      grep -qF 'candidate_shards' .github/workflows/build.yml
      ! grep -qF 'finite-classify-ci' .github/workflows/build.yml
      grep -qF -- '--no-renames' lib/ci-applications/classify-ci.nix
      grep -qF 'fromJSON(needs.prepare.outputs.plan' .github/workflows/build.yml
      grep -qF '.validation.images.required' .github/workflows/build.yml
      grep -qF '.publication.builds.root' .github/workflows/build.yml
      grep -qF "'finite-publication'" .github/workflows/build.yml
      grep -qF 'group: finite-publication' .github/workflows/release.yml
      grep -qF 'finite-image-sign' .github/workflows/build-profile.yml
      ! grep -qF 'cosign sign' .github/workflows/build-profile.yml
      yq -e '
        .jobs.attest.steps[] |
        select(.name == "Restore or generate software bill of materials") |
        .run | select(contains("finite-image-sbom"))
      ' .github/workflows/attest-software-bill-of-materials.yml >/dev/null
      yq -e '
        [.jobs.attest.steps[] |
          select(.uses == "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6")] |
        length | select(. == 2)
      ' .github/workflows/attest-software-bill-of-materials.yml >/dev/null
      ! grep -R -qF 'LEGACY_IMAGE_REF' .github lib
      grep -qF 'payload_source_url#https://github.com/' lib/installer-application.nix
      grep -qF 'finite-sbom-attestation' lib/ci-applications/release-control.nix
      grep -qF 'SBOM_SIGNER_WORKFLOW' lib/ci-applications/sbom-operations.nix
      ! grep -R -qF -- '-sbom-cache' .github automation
      ! grep -R -qF 'Store SBOM cache artifact' .github
      grep -qF 'finite-release-notes' .github/workflows/release.yml
      grep -qF '!= *-dev.*' lib/ci-applications/release-control.nix
      grep -qF 'source_version%%-dev.*' lib/ci-applications/release-control.nix
      grep -qF 'selected_bump=staged' lib/ci-applications/release-control.nix
      grep -qF 'must be newer than' lib/ci-applications/release-control.nix
      ! grep -R -qF 'toolset:' .github
      grep -qF 'finite-ci-gate' .github/workflows/build.yml
      grep -qF 'finite-promote-images' .github/workflows/build.yml
      ! grep -R -Eq 'needs\.(changes|check|plan)|inputs\.publish|publish: true' .github/workflows
      grep -qF 'attest-software-bill-of-materials.yml' .github/workflows/build.yml
      grep -qF 'attest-software-bill-of-materials.yml' lib/installer-application.nix
      grep -qF 'attest-software-bill-of-materials.yml' .github/workflows/release.yml
      grep -qF 'DeterminateSystems/determinate-nix-action@527f17dd63d2d60d3e5552934bc84b9a33a14d11' \
        .github/actions/setup-nix/action.yml
      grep -qF 'max-jobs = 4' .github/actions/setup-nix/action.yml
      grep -qF 'cores = 1' .github/actions/setup-nix/action.yml
      ! grep -qF -- '--out-link /tmp/finite-workflow-toolset' .github/actions/setup-nix/action.yml
      grep -qF '.#ci-github-actions-secrets' .github/actions/setup-nix/action.yml
      grep -qF 'GITHUB_ACTIONS_CACHIX_AUTH_TOKEN' .github/actions/setup-nix/action.yml
      [[ "$(grep -R -h -oF 'secrets.CACHIX_AUTH_TOKEN' .github | wc -l)" == 1 ]]
      [[ "$(grep -R -h -oF 'secrets.MERGE_QUEUE_TOKEN' .github | wc -l)" == 7 ]]
      [[ "$(grep -R -h -oF 'require-merge-queue-token: "true"' \
        .github/workflows | wc -l)" == 7 ]]
      ! grep -R -qF 'token: ''${{ secrets.MERGE_QUEUE_TOKEN' .github
      ! grep -R -qF 'MERGE_QUEUE_TOKEN || github.token' .github/workflows
      grep -qF 'GH_TOKEN: ''${{ env.MERGE_QUEUE_TOKEN }}' \
        .github/workflows/queue-dependabot.yml
      ! grep -qF 'nix profile add' .github/actions/setup-nix/action.yml
      ! grep -R -Eq 'runtimeInputs[[:space:]]*=.*[^[:alnum:]_-]nix([^[:alnum:]_-]|$)' \
        lib/ci-applications lib/flake-applications.nix
      grep -qF 'timeout-minutes: 15' .github/workflows/build.yml
      yq -e '
        .jobs.prepare.steps[] |
        select(.uses == "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1") |
        .with["fetch-depth"] != 0
      ' .github/workflows/build.yml >/dev/null
      yq -e '
        .jobs.checks.steps[] |
        select(.uses == "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1") |
        (.with | has("fetch-depth") | not)
      ' .github/workflows/build.yml >/dev/null
      for cache_assertion in \
        '.if | contains("inputs.cache-write")' \
        '.if | contains("github.ref")' \
        '.if | contains("refs/heads/main")' \
        '.if | contains("pull_request") | not' \
        '.with | has("restore-keys") | not'; do
        yq -e ".runs.steps[] |
          select(.name == \"Save exact installer seed artifacts\") |
          ''${cache_assertion}" \
          .github/actions/save-installer-seed/action.yml >/dev/null
      done
      yq -e '
        .runs.steps[] |
        select(.name == "Apply trusted installer seed cache-save policy") |
        (.uses == "./.github/actions/save-installer-seed" and
          .with["cache-hit"] == "''${{ steps.seed-actions-cache.outputs.cache-hit }}" and
          .with["cache-key"] == "''${{ steps.seed-actions-cache.outputs.cache-primary-key }}" and
          .with["cache-write"] == "''${{ inputs.cache-write }}")
      ' .github/actions/build-installer/action.yml >/dev/null
      grep -qF '"additionalProperties": false' lib/ci-applications/ci-plan.schema.json
      grep -qF -- "--option 'packages:pkgs!'" docs/ci-and-releases.md
      grep -qF -- '--build-context "finite-generated=' lib/ci-applications/profile-stage.nix
      grep -qF 'RUN --mount=type=bind,from=finite-generated,source=.,target=/run/finite-generated' \
        bootc/Containerfile
      grep -qF 'containerfile=./bootc/Containerfile' lib/ci-applications/profile-stage.nix
      grep -qF 'finite-installer-build' .github/actions/build-installer/action.yml
      grep -qF 'name: Classify and plan' .github/workflows/build.yml
      grep -qF 'name: Validate repository and workflows' .github/workflows/build.yml
      grep -qF 'needs: [prepare, checks, build-candidate' .github/workflows/build.yml
      grep -qF 'CHECKS_RESULT: ''${{ needs.checks.result }}' .github/workflows/build.yml
      grep -qF 'installer-cache:' .github/workflows/build.yml
      grep -qF 'cache-write: true' .github/workflows/build.yml
      grep -qF 'end-to-end:' .github/actions/build-installer/action.yml
      grep -qF 'finite-installer-e2e install' .github/actions/build-installer/action.yml
      grep -qF 'finite-installer-e2e boot' .github/actions/build-installer/action.yml
      grep -qF 'finite-dakota-netinstaller-seed-v2' lib/installer-application.nix
      grep -qF 'build-live-squashfs.sh' lib/installer-application.nix
      grep -qF 'live/src/build-iso.sh' lib/installer-application.nix
      grep -qF -- '--layers=false' lib/installer-application.nix
      grep -qF 'oras push' lib/installer-application.nix
      grep -qF 'Restore exact installer seed artifacts' .github/actions/build-installer/action.yml
      ! grep -qF 'bootc-generic-iso' lib/installer-application.nix
      ! grep -qF -- '--bootc-installer-payload-ref' lib/installer-application.nix
      ! grep -qF 'oci-archive:' lib/installer-application.nix
      grep -qF 'root_exec=(sudo)' lib/installer-application.nix
      ! grep -qF 'root_exec=(run0)' lib/installer-application.nix
      ! grep -R -qw 'run0' README.md docs
      grep -qF 'ConditionPathExists=/etc/bootc-installer/finite-netinstall-mode' \
        installer/live/finite/configure-live.d.sh
      grep -qF 'WantedBy=graphical-session.target' \
        installer/live/finite/configure-live.d.sh
      grep -qF 'Installer::Main INFO: do_activate called' \
        installer/live/finite/configure-live.d.sh
      grep -qF '/etc/xdg/autostart/tuna-installer.desktop' \
        installer/live/finite/configure-live.d.sh
      grep -qF 'systemctl disable live-ready.service' installer/live/finite/configure-live.d.sh
      grep -qF 'finite-installer-target-config.service' \
        installer/live/finite/configure-live.d.sh
      grep -qF 'projectbluefin/bootc-installer' lib/installer-application.nix
      grep -qF 'seed-cache-hit=' lib/installer-application.nix
      grep -qF 'checks.' modules/outputs.nix
      grep -qF 'repositoryChecks' modules/outputs.nix
      [[ "$(grep -cF 'steps.plan.outputs.plan' .github/workflows/build.yml)" == 1 ]]
      ! grep -Eq 'outputs\.(lifecycle|matrix|root_matrix|hardware_matrix|role_matrix)' \
        .github/workflows/build.yml

      if grep -R -Eq '(automation/[^ ]+\.sh|bootc/builder/(reuse-image|sbom)\.sh)' \
        .github lib; then
        echo 'A removed raw automation entrypoint is still referenced' >&2
        exit 1
      fi
      ! find tests/repository -maxdepth 1 -type f \
        \( -name 'architecture.sh' -o -name 'aspects.sh' -o -name 'automation.sh' -o \
        -name 'bootc.sh' -o -name 'documentation.sh' -o -name 'nix.sh' -o \
        -name 'release.sh' -o -name 'shell.sh' -o -name 'upstream.sh' -o \
        -name 'workflows.sh' \) | grep -q .

      for workflow in .github/workflows/*.yml; do
        yq -e 'has("jobs") and (.jobs | length > 0)' "''${workflow}" >/dev/null
      done

      [[ "$(grep -cF 'gh attestation verify "oci://' lib/installer-application.nix)" == \
        "$(grep -cF -- '--bundle-from-oci' lib/installer-application.nix)" ]]
      [[ "$(grep -cF 'gh_command}" attestation verify' \
        lib/ci-applications/image-verify.nix)" == \
        "$(grep -cF -- '--bundle-from-oci' lib/ci-applications/image-verify.nix)" ]]
      grep -qF 'gh_command}" attestation verify' lib/ci-applications/image-verify.nix
      grep -qF -- '--bundle-from-oci' lib/ci-applications/image-verify.nix

      actionlint -color .github/workflows/*.yml
      zizmor --offline --no-config --collect=all .github
    '';
  };

  nix = mkSourceCheck {
    name = "nix-checks";
    source = nixSource;
    tools = with pkgs; [gnugrep ripgrep statix];
    commands = ''
      set -euo pipefail

      statix check .
      ! grep -qF 'features.users' modules/profiles/definitions.nix
      grep -qF 'home-bluefin-dx' lib/domain-catalog.nix
      ! grep -qF 'import ../flake.nix' modules/outputs.nix
      ! grep -qF 'import inputs.nixpkgs' modules/outputs.nix
      ! grep -qF 'import finiteInputs.nixpkgs' lib/home-manager-flake-module.nix
      grep -qF 'mkPkgs system' modules/outputs.nix
      grep -qF 'mkPkgs system' lib/home-manager-flake-module.nix
      ! rg -qF 'extraSpecialArgs.inputs' lib modules
      grep -qF 'finiteHomeDependencies = homeDependencies' lib/home-manager-flake-module.nix
      grep -qF '_module.args' modules/den.nix
      grep -qF 'class = "bootc"' modules/profiles/schema.nix
      grep -qF 'class = "bootc"' lib/eval-profile-graph.nix
      grep -qF '_class = "bootc"' modules/profiles/bootc-class.nix
      grep -qF 'exportTable = {' modules/outputs.nix
      grep -qF 'packages.''${system} = packageExports' modules/outputs.nix
      grep -qF 'apps.''${system} = appExports' modules/outputs.nix
      grep -qF 'foundationHardwareProofs' modules/outputs.nix
      grep -qF 'allRolesProof' modules/outputs.nix
    '';
  };
}
