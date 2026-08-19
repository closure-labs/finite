{
  applications,
  architecture,
  generated,
  lib,
  pkgs,
}: let
  root = ../.;
  inherit (lib) fileset;
  sourceFor = selected:
    fileset.toSource {
      inherit root;
      fileset = fileset.unions selected;
    };
  shellFiles = fileset.fileFilter (file: file.type == "regular" && lib.hasSuffix ".sh" file.name) root;
  nixFiles = fileset.fileFilter (file: file.type == "regular" && lib.hasSuffix ".nix" file.name) root;
  textFiles =
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
    root;
  shellSource = sourceFor [shellFiles];
  nixSource = sourceFor [nixFiles];
  repositorySource = sourceFor [
    ../VERSION
    ../bootc/Containerfile
    ../bootc/Containerfile.derived
    ../bootc/builder
    ../modules/aspects
    ../sources
    ../secretspec.toml
    ../tests/repository/contracts.sh
  ];
  documentationSource = sourceFor [textFiles];
  automationSource = sourceFor [
    ../flake.nix
    ../tests/automation
  ];
  bootcSource = sourceFor [
    ../.github/syft.yaml
    ../bootc/builder
    ../flake.nix
    ../modules/aspects
    ../tests/bootc
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
    ../flake.nix
    ../lib/flake-applications.nix
    ../modules/outputs.nix
    ../sources
    ../secretspec.toml
  ];
  workflowSource = sourceFor [
    ../.github
    ../lib/ci-applications
    ../lib/flake-applications.nix
    ../automation/github/policies
    ../bootc/Containerfile
    ../flake.nix
    ../lib/installer-application.nix
    ../modules/outputs.nix
    ../installer/Containerfile
    ../installer/rootfs/usr/share/anaconda/interactive-defaults.ks
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
      grep -qF 'profiles_dale --> features_roles_support' ${architecture}/namespace.mmd
      grep -qF 'operations_github_build --> operations_checks_all' ${architecture}/namespace.mmd
      grep -qF 'operations_checks_all --> operations_checks_repository_contracts' ${architecture}/namespace.mmd
      grep -qF 'operations_checks_all --> operations_checks_bootc_engine' ${architecture}/namespace.mmd
      grep -qF 'operations_github_build --> operations_delivery_installer' ${architecture}/namespace.mmd
      grep -qF 'operations_updates_bluefin --> sources_bluefin' ${architecture}/namespace.mmd
      grep -qF 'operations_github_bluefin_update --> operations_updates_bluefin' ${architecture}/namespace.mmd
      grep -qF 'operations_updates_determinate_nix --> sources_determinate_nix' ${architecture}/namespace.mmd
      grep -qF 'operations_github_determinate_nix_update --> operations_updates_determinate_nix' \
        ${architecture}/namespace.mmd
    '';
  };

  upstream = mkSourceCheck {
    name = "upstream-contracts";
    source = upstreamSource;
    tools = with pkgs; [gnugrep jq secretspec];
    commands = ''
      # shellcheck disable=SC2016,SC2251
      set -euo pipefail

      jq -e '
        .schema == 1 and
        .image == "ghcr.io/projectbluefin/bluefin" and
        .tag == "stable" and
        .architecture == "amd64" and
        (.digest | test("^sha256:[0-9a-f]{64}$")) and
        (.cosign.issuer | startswith("https://")) and
        (.cosign.identity | startswith("https://"))
      ' sources/bluefin.json >/dev/null
      jq -e '
        .schema == 1 and
        .image == "ghcr.io/osbuild/image-builder-cli" and
        .tag == "latest" and
        .architecture == "amd64" and
        (.digest | test("^sha256:[0-9a-f]{64}$"))
      ' sources/image-builder.json >/dev/null
      jq -e '
        .schema == 1 and
        .architecture == "x86_64-linux" and
        (.version | test("^[0-9]+\\.[0-9]+\\.[0-9]+$")) and
        (.installer.url | startswith("https://github.com/DeterminateSystems/nix-installer/releases/download/")) and
        (.installer.sha256 | test("^[0-9a-f]{64}$")) and
        (.selinuxPolicy.url | startswith("https://raw.githubusercontent.com/DeterminateSystems/nix-installer/")) and
        (.selinuxPolicy.sha256 | test("^[0-9a-f]{64}$"))
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
      grep -qF 'nix --accept-flake-config build --no-link' lib/flake-applications.nix
      grep -qF 'max_closure_size=$((1024 * 1024))' lib/flake-applications.nix
      ! grep -qF 'dockerTools.pullImage' modules/outputs.nix
      ! grep -qF 'bluefin-upstream' modules/outputs.nix
      grep -qF 'skopeo copy' lib/flake-applications.nix
      grep -qF 'containers-storage:' lib/flake-applications.nix
      grep -qF 'host_podman' lib/flake-applications.nix
      grep -qF 'unshare "$0"' lib/flake-applications.nix
      grep -qF 'https://purplefin.cachix.org' flake.nix
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
      applications.ciGate
      applications.promoteImages
      applications.trustedUpdate
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
    '';
  };

  bootc = mkSourceCheck {
    name = "bootc-checks";
    source = bootcSource;
    generatedRoot = generated;
    tools = with pkgs; [
      applications.imagePlan
      applications.imageReuse
      applications.imageSbom
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
      bash tests/bootc/reuse-image.sh
      bash tests/bootc/sbom.sh
      bash tests/bootc/shards.sh
    '';
  };

  aspects = mkSourceCheck {
    name = "aspect-contracts";
    source = aspectsSource;
    tools = with pkgs; [gnugrep systemd util-linux];
    commands = ''
      set -euo pipefail

      bash modules/aspects/base/tests/contracts.sh
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

      grep -qF 'nix run .#ci' .github/workflows/build.yml
      for updater in update-bluefin.yml update-determinate-nix.yml update-flake-lock.yml update-image-builder.yml; do
        grep -qF 'nix run .#trusted-update' ".github/workflows/''${updater}"
      done
      [[ "$(grep -cF 'purplefin-trusted-update' .github/workflows/release.yml)" == 2 ]]
      [[ "$(grep -cF 'SOURCE_SHA: ''${{ steps.source.outputs.source_sha }}' .github/workflows/release.yml)" == 2 ]]
      ! grep -qF 'steps.version.outputs.source_sha' .github/workflows/release.yml
      ! grep -qF 'git push origin HEAD:main' .github/workflows/release.yml
      ! grep -R -qF 'github-actions[bot]' .github/workflows
      grep -qF 'nix run .#source-update -- bluefin' .github/workflows/update-bluefin.yml
      grep -qF 'nix run .#source-update -- determinate-nix' .github/workflows/update-determinate-nix.yml
      grep -qF 'nix run .#source-update -- image-builder' .github/workflows/update-image-builder.yml
      grep -qF 'nix run .#source-update -- flake' .github/workflows/update-flake-lock.yml
      grep -qF 'purplefin-load-bluefin' .github/workflows/build-profile.yml
      grep -qF 'purplefin-ci-plan' .github/workflows/build.yml
      grep -qF 'purplefin-validate-image-shard' .github/workflows/build.yml
      grep -qF 'candidate_shards' .github/workflows/build.yml
      grep -qF 'purplefin-classify-ci' .github/workflows/build.yml
      grep -qF 'purplefin-image-reuse' .github/workflows/build-profile.yml
      grep -qF 'purplefin-image-sbom' .github/workflows/attest-software-bill-of-materials.yml
      grep -qF 'purplefin-sbom-attestation' .github/workflows/release.yml
      grep -qF 'SBOM_SIGNER_WORKFLOW' lib/flake-applications.nix
      ! grep -R -qF -- '-sbom-cache' .github automation
      ! grep -R -qF 'Store SBOM cache artifact' .github
      grep -qF 'purplefin-release-notes' .github/workflows/release.yml
      grep -qF 'toolset: workflow-prepare' .github/workflows/build.yml
      grep -qF 'toolset: workflow-validation' .github/workflows/build.yml
      grep -qF 'toolset: workflow-publish' .github/workflows/build-profile.yml
      grep -qF 'toolset: workflow-sbom' .github/workflows/attest-software-bill-of-materials.yml
      grep -qF 'purplefin-ci-gate' .github/workflows/build.yml
      grep -qF 'toolset: workflow-gate' .github/workflows/build.yml
      grep -qF 'purplefin-promote-images' .github/workflows/build.yml
      ! grep -R -Eq 'needs\.(changes|check|plan)|inputs\.publish|publish: true' .github/workflows
      grep -qF 'attest-software-bill-of-materials.yml' .github/workflows/build.yml
      grep -qF 'attest-software-bill-of-materials.yml' lib/installer-application.nix
      grep -qF 'attest-software-bill-of-materials.yml' .github/workflows/release.yml
      grep -qF 'toolset: workflow-release' .github/workflows/release.yml
      grep -qF 'cachix/install-nix-action@13d8dd58da0234aa297dedd986986ccb8e7f3e24' \
        .github/actions/setup-nix/action.yml
      grep -qF 'cachix/cachix-action@5f2d7c5294214f71b873db4b969586b980625e71' \
        .github/actions/setup-nix/action.yml
      grep -qF 'nix build --accept-flake-config' .github/actions/setup-nix/action.yml
      grep -qF -- '--out-link /tmp/purplefin-workflow-toolset' .github/actions/setup-nix/action.yml
      grep -qF 'nix run --accept-flake-config .#github-actions-secrets' .github/actions/setup-nix/action.yml
      grep -qF 'authToken: ''${{ env.CACHIX_AUTH_TOKEN }}' .github/actions/setup-nix/action.yml
      [[ "$(grep -R -h -oF 'secrets.CACHIX_AUTH_TOKEN' .github | wc -l)" == 1 ]]
      [[ "$(grep -R -h -oF 'secrets.MERGE_QUEUE_TOKEN' .github | wc -l)" == 5 ]]
      ! grep -R -qF 'token: ''${{ secrets.MERGE_QUEUE_TOKEN' .github
      grep -qF 'GH_TOKEN: ''${{ env.MERGE_QUEUE_TOKEN || github.token }}' \
        .github/workflows/queue-dependabot.yml
      ! grep -qF 'nix profile add' .github/actions/setup-nix/action.yml
      ! grep -R -qF 'DeterminateSystems/determinate-nix-action' .github
      grep -qF -- '--build-context purplefin-generated=' .github/workflows/build-profile.yml
      grep -qF 'RUN --mount=type=bind,from=purplefin-generated,source=.,target=/run/purplefin-generated' \
        bootc/Containerfile
      grep -qF 'containerfile=./bootc/Containerfile' .github/workflows/build-profile.yml
      grep -qF 'purplefin-installer-build' .github/actions/build-installer/action.yml
      grep -qF -- '--build-context installer-rootfs=installer/rootfs' lib/installer-application.nix
      grep -qF 'RUN --mount=from=installer-rootfs,target=/run/installer-rootfs' installer/Containerfile
      grep -qF '@@INSTALLER_PAYLOAD_SOURCE_REF@@' \
        installer/rootfs/usr/share/anaconda/interactive-defaults.ks
      grep -qF 'checks.''${system} =' modules/outputs.nix
      grep -qF 'repositoryChecks' modules/outputs.nix

      for executable in \
        ${applications.workflowPrepare}/bin/purplefin-classify-ci \
        ${applications.workflowPrepare}/bin/purplefin-ci-plan \
        ${applications.workflowValidation}/bin/purplefin-validate-image-shard \
        ${applications.workflowPublish}/bin/purplefin-image-reuse \
        ${applications.workflowPublish}/bin/purplefin-load-bluefin \
        ${applications.workflowPublish}/bin/purplefin-promote-images \
        ${applications.workflowInstaller}/bin/purplefin-installer-build \
        ${applications.workflowSbom}/bin/purplefin-image-sbom \
        ${applications.workflowRelease}/bin/purplefin-release-notes \
        ${applications.workflowRelease}/bin/purplefin-sbom-attestation \
        ${applications.workflowRelease}/bin/purplefin-trusted-update \
        ${applications.workflowGate}/bin/purplefin-ci-gate; do
        test -x "''${executable}"
      done

      previous_line=0
      for output in \
        base_image base_digest base_tag base_sbom_matrix candidate_shards \
        hardware_matrix hardware_sbom_matrix has_hardware has_builds has_roles \
        has_root_base has_base_sbom has_hardware_sbom has_role_sbom matrix \
        role_matrix role_sbom_matrix root_base version; do
        line="$(grep -nF "printf '$output=%s" lib/flake-applications.nix | cut -d: -f1)"
        test -n "''${line}"
        ((line > previous_line))
        previous_line="''${line}"
      done
      grep -qF "printf 'images=%s\\ninstaller=%s\\n'" lib/flake-applications.nix

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
