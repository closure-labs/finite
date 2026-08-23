{
  applications,
  architecture,
  generated,
  lib,
  pkgs,
  secretspec,
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
    ../VERSION
    ../bootc/Containerfile
    ../bootc/Containerfile.derived
    ../bootc/builder
    ../modules/aspects
    ../modules/outputs.nix
    ../sources
    ../secretspec.toml
    ../tests/repository/contracts.sh
  ];
  documentationSource = sourceFor [textFiles];
  automationSource = sourceFor [
    ../docs/ci-and-releases.md
    ../docs/configuration.md
    ../docs/installation.md
    ../flake.lock
    ../flake.nix
    ../lib/ci-applications/validate-locks.nix
    ../modules/outputs.nix
    ../tests/automation
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
    ../flake.nix
    ../installer
    ../lib/ci-applications/installer-e2e.nix
    ../lib/ci-applications/installer-smoke.nix
    ../lib/installer-application.nix
    ../sources/image-builder.json
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
    ../lib/flake-applications.nix
    ../modules/outputs.nix
    ../modules/profiles/definitions.nix
    ../sources
    ../secretspec.toml
  ];
  workflowSource = sourceFor [
    ../.github
    ../devenv-tasks.nix
    ../devenv.nix
    ../devenv.yaml
    ../docs/ci-and-releases.md
    ../lib/ci-applications
    ../lib/flake-applications.nix
    ../automation/github/policies
    ../bootc/Containerfile
    ../flake.nix
    ../lib/installer-application.nix
    ../modules/outputs.nix
    ../installer/Containerfile
    ../installer/rootfs/usr/share/anaconda/interactive-defaults.ks
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
    pkgs.runCommand "purplefin-${name}" {
      nativeBuildInputs = [pkgs.bash pkgs.coreutils] ++ tools;
    } ''
      export HOME="$TMPDIR/home"
      mkdir -p "$HOME" source
      cp -R ${source}/. source/
      chmod -R u+w source
      cd source
      ${lib.optionalString (generatedRoot != null) ''
        export PURPLEFIN_GENERATED_ROOT=${generatedRoot}
      ''}
      export PURPLEFIN_HERMETIC_CHECK=true
      export PURPLEFIN_SOURCE_ROOT="$PWD"
      ${commands}
      touch "$out"
    '';
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
    tools = with pkgs; [gnugrep jq];
    commands = ''
      bash tests/repository/contracts.sh
      for profile in dale elad; do
        for role in sales executive developer support it trainer; do
          grep -qF "profiles_home_''${profile} --> features_roles_''${role}" ${architecture}/namespace.mmd
        done
      done
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
      grep -qF 'operations_delivery_installer --> sources_fedora_bootc' ${architecture}/namespace.mmd
      grep -qF 'operations_delivery_installer --> sources_image_builder' ${architecture}/namespace.mmd
      grep -qF 'operations_updates_fedora_bootc --> sources_fedora_bootc' ${architecture}/namespace.mmd
      grep -qF 'operations_github_fedora_bootc_update --> operations_updates_fedora_bootc' \
        ${architecture}/namespace.mmd
    '';
  };

  upstream = mkSourceCheck {
    name = "upstream-contracts";
    source = upstreamSource;
    tools = with pkgs; [gnugrep jq] ++ [secretspec];
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
        .schema == 1 and
        .image == "ghcr.io/osbuild/image-builder-cli" and
        .tag == "latest" and
        .architecture == "amd64" and
        (.digest | test("^sha256:[0-9a-f]{64}$"))
      ' sources/image-builder.json >/dev/null
      jq -e '
        .schema == 1 and
        .image == "quay.io/fedora/fedora-bootc" and
        .tag == "44" and
        .architecture == "amd64" and
        (.digest | test("^sha256:[0-9a-f]{64}$"))
      ' sources/fedora-bootc.json >/dev/null
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
      secretspec schema --file secretspec.toml --profile local-cache |
        jq -e '.required == ["CACHIX_AUTH_TOKEN"]' >/dev/null
      secretspec schema --file secretspec.toml --profile github-actions |
        jq -e '
          .required == [] and
          (.properties | keys == ["CACHIX_AUTH_TOKEN", "MERGE_QUEUE_TOKEN"])
        ' >/dev/null
      grep -qF 'github-actions = "env"' secretspec.toml
      grep -qF 'ref = { item = "GITHUB_ACTIONS_CACHIX_AUTH_TOKEN" }' secretspec.toml
      grep -qF 'ref = { item = "GITHUB_ACTIONS_MERGE_QUEUE_TOKEN" }' secretspec.toml
      ! grep -qF 'cachix watch-exec' lib/flake-applications.nix
      grep -qF 'cachix push --omit-deriver purplefin' lib/flake-applications.nix
      grep -qF 'selfFlakeUri = "path:''${toString selfSource}"' lib/flake-applications.nix
      ! grep -qF 'unsafeDiscardStringContext' lib/flake-applications.nix
      grep -qF 'nix --accept-flake-config eval --json' lib/flake-applications.nix
      ! grep -qF 'quotedPaths' lib/flake-applications.nix
      grep -qF 'flake_uri="git+file://' lib/flake-applications.nix
      grep -qF -- '--no-build' lib/flake-applications.nix
      grep -qF 'nix --accept-flake-config build' lib/flake-applications.nix
      grep -qF -- '--no-link' lib/flake-applications.nix
      grep -qF '#ci-checks"' lib/flake-applications.nix
      [[ "$(grep -m1 -nF 'nix --accept-flake-config build' lib/flake-applications.nix | cut -d: -f1)" -lt \
        "$(grep -m1 -nF 'nix --accept-flake-config flake check' lib/flake-applications.nix | cut -d: -f1)" ]]
      grep -qF 'ci-checks = ciChecks' modules/outputs.nix
      grep -qF 'ln -s' modules/outputs.nix
      grep -qF 'max_closure_size=$((1024 * 1024))' lib/flake-applications.nix
      ! grep -qF 'dockerTools.pullImage' modules/outputs.nix
      ! grep -qF 'bluefin-upstream' modules/outputs.nix
      grep -qF 'skopeo copy' lib/flake-applications.nix
      grep -qF 'containers-storage:' lib/flake-applications.nix
      grep -qF 'host_podman' lib/flake-applications.nix
      grep -qF 'unshare "$0"' lib/flake-applications.nix
      grep -qF -- '--label "io.purplefin.build.profile=' lib/flake-applications.nix
      grep -qF 'https://purplefin.cachix.org' flake.nix
      grep -qF 'https://cachix.cachix.org' flake.nix
      grep -qF 'cachix.cachix.org-1:eWNHQldwUO7G2VkjpnjDbWwy4KQ/HNxht7H4SSoMckM=' flake.nix
      grep -qF 'cachix.pull = ["cachix" "purplefin"]' devenv.nix
      grep -qF 'provider: local' devenv.yaml
      grep -qF 'local = "file:~/.other-fun-things"' secretspec.toml
      ! grep -qF 'token_file=' lib/flake-applications.nix
      grep -qF 'runtimeInputs = [devenv secretspec];' lib/flake-applications.nix
      grep -qF 'features.users.dale' modules/profiles/definitions.nix
      grep -qF 'home.packages = [(lib.lowPrio weeklyPkgs.secretspec)];' modules/profiles/definitions.nix
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
      applications.promoteImages
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
      bash tests/automation/promote-images.sh
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
        ${applications.rechunkImage}/bin/purplefin-rechunk-image
      bash tests/bootc/reuse-image.sh
      bash tests/bootc/sign-image.sh
      bash tests/bootc/sbom.sh
      bash tests/bootc/shards.sh
    '';
  };

  installer = mkSourceCheck {
    name = "installer-contracts";
    source = installerSource;
    tools = [pkgs.gnugrep pkgs.gnused pkgs.jq pkgs.pykickstart pkgs.python3];
    commands = ''
      set -euo pipefail

      bash tests/installer/contracts.sh \
        ${applications.installerBuild}/bin/purplefin-installer-build
      python3 tests/installer/squashfs-stage.py
      bash tests/installer/smoke.sh \
        ${applications.installerSmoke}/bin/purplefin-installer-smoke
      bash tests/installer/e2e.sh \
        ${applications.installerE2e}/bin/purplefin-installer-e2e
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
      release_notes="$(purplefin-release-notes "''${latest_changelog_version}" CHANGELOG.md)"
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
    source = workflowSource;
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

      grep -qF 'nix shell --accept-flake-config .#ci-check' .github/workflows/build.yml
      grep -qF 'nix shell --accept-flake-config .#ci-prepare' .github/workflows/build.yml
      for updater in \
        update-bluefin.yml \
        update-determinate-nix.yml \
        update-fedora-bootc.yml \
        update-flake-lock.yml \
        update-home-release.yml \
        update-image-builder.yml; do
        grep -qF '.#ci-trusted-update' ".github/workflows/''${updater}"
      done
      [[ "$(grep -cF 'purplefin-trusted-update' .github/workflows/release.yml)" == 2 ]]
      [[ "$(grep -cF 'SOURCE_SHA: ''${{ steps.source.outputs.source_sha }}' .github/workflows/release.yml)" == 2 ]]
      ! grep -qF 'steps.version.outputs.source_sha' .github/workflows/release.yml
      ! grep -qF 'git push origin HEAD:main' .github/workflows/release.yml
      ! grep -R -qF 'github-actions[bot]' .github/workflows
      grep -qF 'purplefin-source-update bluefin ' .github/workflows/update-bluefin.yml
      grep -qF 'purplefin-source-update bluefin-dx ' .github/workflows/update-bluefin.yml
      grep -qF 'purplefin-source-update determinate-nix ' .github/workflows/update-determinate-nix.yml
      grep -qF 'purplefin-source-update fedora-bootc ' .github/workflows/update-fedora-bootc.yml
      grep -qF 'purplefin-source-update image-builder ' .github/workflows/update-image-builder.yml
      grep -qF 'purplefin-update-locks ' .github/workflows/update-flake-lock.yml
      grep -qF 'purplefin-update-home-release ' .github/workflows/update-home-release.yml
      grep -qF 'purplefin-load-bluefin' .github/workflows/build-profile.yml
      grep -qF 'purplefin-ci-prepare' .github/workflows/build.yml
      grep -qF 'purplefin-validate-image-shard' .github/workflows/build.yml
      grep -qF 'candidate_shards' .github/workflows/build.yml
      ! grep -qF 'purplefin-classify-ci' .github/workflows/build.yml
      grep -qF -- '--no-renames' lib/ci-applications/classify-ci.nix
      grep -qF 'fromJSON(needs.prepare.outputs.plan' .github/workflows/build.yml
      grep -qF '.validation.images.required' .github/workflows/build.yml
      grep -qF '.publication.builds.root' .github/workflows/build.yml
      grep -qF "'purplefin-publication'" .github/workflows/build.yml
      grep -qF 'group: purplefin-publication' .github/workflows/release.yml
      grep -qF 'purplefin-image-reuse' .github/workflows/build-profile.yml
      grep -qF 'purplefin-image-sign' .github/workflows/build-profile.yml
      grep -qF 'purplefin-rechunk-image' .github/workflows/build-profile.yml
      ! grep -qF 'cosign sign' .github/workflows/build-profile.yml
      grep -qF 'purplefin-image-sbom' .github/workflows/attest-software-bill-of-materials.yml
      grep -qF 'LEGACY_IMAGE_REF: ghcr.io/declarative-dale/purplefin' .github/actions/build-installer/action.yml
      grep -qF 'payload_source_url#https://github.com/' lib/installer-application.nix
      grep -qF 'purplefin-sbom-attestation' .github/workflows/release.yml
      grep -qF 'SBOM_SIGNER_WORKFLOW' lib/flake-applications.nix
      ! grep -R -qF -- '-sbom-cache' .github automation
      ! grep -R -qF 'Store SBOM cache artifact' .github
      grep -qF 'purplefin-release-notes' .github/workflows/release.yml
      grep -qF 'if [[ "''${source_version}" != *-dev.* ]]; then' .github/workflows/release.yml
      grep -qF 'version="''${source_version}"' .github/workflows/release.yml
      grep -qF 'selected_bump="staged"' .github/workflows/release.yml
      grep -qF 'Staged release ''${version} must be newer than ''${last_version}' \
        .github/workflows/release.yml
      ! grep -R -qF 'toolset:' .github
      grep -qF 'purplefin-ci-gate' .github/workflows/build.yml
      grep -qF 'purplefin-promote-images' .github/workflows/build.yml
      ! grep -R -Eq 'needs\.(changes|check|plan)|inputs\.publish|publish: true' .github/workflows
      grep -qF 'attest-software-bill-of-materials.yml' .github/workflows/build.yml
      grep -qF 'attest-software-bill-of-materials.yml' lib/installer-application.nix
      grep -qF 'attest-software-bill-of-materials.yml' .github/workflows/release.yml
      grep -qF 'DeterminateSystems/determinate-nix-action@668647a33843b1f280cb2ef4c41736f86b29f826' \
        .github/actions/setup-nix/action.yml
      grep -qF 'cachix/cachix-action@5f2d7c5294214f71b873db4b969586b980625e71' \
        .github/actions/setup-nix/action.yml
      ! grep -qF -- '--out-link /tmp/purplefin-workflow-toolset' .github/actions/setup-nix/action.yml
      grep -qF '.#ci-github-actions-secrets' .github/actions/setup-nix/action.yml
      grep -qF 'authToken: ''${{ env.CACHIX_AUTH_TOKEN }}' .github/actions/setup-nix/action.yml
      [[ "$(grep -R -h -oF 'secrets.CACHIX_AUTH_TOKEN' .github | wc -l)" == 1 ]]
      [[ "$(grep -R -h -oF 'secrets.MERGE_QUEUE_TOKEN' .github | wc -l)" == 7 ]]
      ! grep -R -qF 'token: ''${{ secrets.MERGE_QUEUE_TOKEN' .github
      grep -qF 'GH_TOKEN: ''${{ env.MERGE_QUEUE_TOKEN || github.token }}' \
        .github/workflows/queue-dependabot.yml
      ! grep -qF 'nix profile add' .github/actions/setup-nix/action.yml
      ! grep -R -Eq 'runtimeInputs[[:space:]]*=.*[^[:alnum:]_-]nix([^[:alnum:]_-]|$)' \
        lib/ci-applications lib/flake-applications.nix
      grep -qF 'timeout-minutes: 15' .github/workflows/build.yml
      [[ "$(grep -cF 'fetch-depth: 0' .github/workflows/build.yml)" == 1 ]]
      ! grep -qF 'fetch-depth: >-' .github/workflows/build.yml
      grep -qF '"additionalProperties": false' lib/ci-applications/ci-plan.schema.json
      grep -qF -- "--option 'packages:pkgs!'" docs/ci-and-releases.md
      grep -qF -- '--build-context purplefin-generated=' .github/workflows/build-profile.yml
      grep -qF 'RUN --mount=type=bind,from=purplefin-generated,source=.,target=/run/purplefin-generated' \
        bootc/Containerfile
      grep -qF 'containerfile=./bootc/Containerfile' .github/workflows/build-profile.yml
      grep -qF 'purplefin-installer-build' .github/actions/build-installer/action.yml
      grep -qF 'installer-cache:' .github/workflows/build.yml
      grep -qF 'cache-write: true' .github/workflows/build.yml
      grep -qF 'end-to-end:' .github/actions/build-installer/action.yml
      grep -qF 'purplefin-installer-e2e install' .github/actions/build-installer/action.yml
      grep -qF 'purplefin-installer-e2e boot' .github/actions/build-installer/action.yml
      grep -qF -- '--build-context installer-rootfs=installer/rootfs' lib/installer-application.nix
      grep -qF 'RUN --mount=from=installer-rootfs,target=/run/installer-rootfs' installer/Containerfile
      grep -qF 'PURPLEFIN_INSTALLER_BASE_REF' lib/installer-application.nix
      grep -qF -- '--build-arg "BASE_REF=' lib/installer-application.nix
      grep -qF -- '--bootc-installer-payload-ref' lib/installer-application.nix
      grep -qF '@@INSTALLER_PAYLOAD_SOURCE_REF@@' \
        installer/rootfs/usr/share/anaconda/interactive-defaults.ks
      grep -qF 'checks.' modules/outputs.nix
      grep -qF 'repositoryChecks' modules/outputs.nix

      for executable in \
        ${applications.ciPrepare}/bin/purplefin-ci-prepare \
        ${applications.validateCiPlan}/bin/purplefin-ci-validate-plan \
        ${applications.validateImageShard}/bin/purplefin-validate-image-shard \
        ${applications.imageReuse}/bin/purplefin-image-reuse \
        ${applications.imageSign}/bin/purplefin-image-sign \
        ${applications.rechunkImage}/bin/purplefin-rechunk-image \
        ${applications.loadBluefin}/bin/purplefin-load-bluefin \
        ${applications.promoteImages}/bin/purplefin-promote-images \
        ${applications.installerBuild}/bin/purplefin-installer-build \
        ${applications.installerE2e}/bin/purplefin-installer-e2e \
        ${applications.imageSbom}/bin/purplefin-image-sbom \
        ${applications.releaseNotes}/bin/purplefin-release-notes \
        ${applications.updateLocks}/bin/purplefin-update-locks \
        ${applications.updateHomeRelease}/bin/purplefin-update-home-release \
        ${applications.sbomAttestation}/bin/purplefin-sbom-attestation \
        ${applications.trustedUpdate}/bin/purplefin-trusted-update \
        ${applications.ciGate}/bin/purplefin-ci-gate; do
        test -x "$executable"
      done
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

      for verifier in lib/installer-application.nix .github/workflows/release.yml; do
        [[ "$(grep -cF 'gh attestation verify "oci://' "''${verifier}")" == \
          "$(grep -cF -- '--bundle-from-oci' "''${verifier}")" ]]
      done
      grep -qF 'gh_command}" attestation verify' lib/flake-applications.nix
      grep -qF -- '--bundle-from-oci' lib/flake-applications.nix

      actionlint -color .github/workflows/*.yml
      zizmor --offline --no-config --collect=all .github
    '';
  };

  nix = mkSourceCheck {
    name = "nix-checks";
    source = nixSource;
    tools = [pkgs.statix];
    commands = ''
      set -euo pipefail

      statix check .
    '';
  };
}
