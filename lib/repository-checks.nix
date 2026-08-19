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
    ../automation/github
    ../tests/automation
  ];
  bootcSource = sourceFor [
    ../.github/syft.yaml
    ../bootc/builder
    ../modules/aspects
    ../tests/bootc
  ];
  aspectsSource = sourceFor [
    ../modules/aspects
  ];
  releaseSource = sourceFor [
    ../CHANGELOG.md
    ../VERSION
    ../automation/release
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
    ../automation/github/policies
    ../bootc/Containerfile
    ../bootc/builder/sbom.sh
    ../flake.nix
    ../lib/installer-application.nix
    ../modules/outputs.nix
    ../installer/Containerfile
    ../installer/rootfs/usr/share/anaconda/interactive-defaults.ks
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
    tools = with pkgs; [findutils shellcheck];
    commands = ''
      mapfile -d $'\0' shell_files < <(
        find automation bootc modules tests \
          -type f -name '*.sh' -print0
      )
      bash -n "''${shell_files[@]}"
      # Dynamic container build roots cannot be followed statically. Every
      # sourced shell file is already present in this complete input array.
      shellcheck --exclude=SC1091 --external-sources --source-path=SCRIPTDIR \
        "''${shell_files[@]}"
    '';
  };

  repository = mkSourceCheck {
    name = "repository-contracts";
    source = repositorySource;
    generatedRoot = generated;
    tools = with pkgs; [gnugrep jq];
    commands = ''
      bash tests/repository/contracts.sh
      grep -qF 'profiles_dale --> features_roles_support' \
        ${architecture}/namespace.mmd
      grep -qF 'operations_github_build --> operations_checks_all' \
        ${architecture}/namespace.mmd
      grep -qF 'operations_checks_all --> operations_checks_repository_contracts' \
        ${architecture}/namespace.mmd
      grep -qF 'operations_checks_all --> operations_checks_bootc_engine' \
        ${architecture}/namespace.mmd
      grep -qF 'operations_github_build --> operations_delivery_installer' \
        ${architecture}/namespace.mmd
      grep -qF 'operations_updates_bluefin --> sources_bluefin' \
        ${architecture}/namespace.mmd
      grep -qF 'operations_github_bluefin_update --> operations_updates_bluefin' \
        ${architecture}/namespace.mmd
    '';
  };

  upstream = mkSourceCheck {
    name = "upstream-contracts";
    source = upstreamSource;
    tools = with pkgs; [gnugrep jq secretspec];
    commands = ''
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
      applications.shardPlan
      applications.validateImageShard
      diffutils
      findutils
      gnugrep
      jq
    ];
    commands = ''
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
      bash modules/aspects/base/tests/contracts.sh
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
    tools = with pkgs; [actionlint gnugrep jq yq-go zizmor];
    commands = ''
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
      grep -qF 'nix run .#trusted-update' .github/workflows/update-flake-lock.yml
      grep -qF 'nix run .#trusted-update' .github/workflows/update-image-builder.yml
      grep -qF 'nix run .#trusted-update' .github/workflows/update-bluefin.yml
      [[ "$(grep -cF 'purplefin-trusted-update' .github/workflows/release.yml)" == 2 ]]
      [[ "$(grep -cF 'SOURCE_SHA: ''${{ steps.source.outputs.source_sha }}' .github/workflows/release.yml)" == 2 ]]
      ! grep -qF 'steps.version.outputs.source_sha' .github/workflows/release.yml
      ! grep -qF 'git push origin HEAD:main' .github/workflows/release.yml
      ! grep -R -qF 'github-actions[bot]' .github/workflows
      grep -qF 'nix run .#source-update -- bluefin' .github/workflows/update-bluefin.yml
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
      grep -qF 'SBOM_SIGNER_WORKFLOW' bootc/builder/sbom.sh
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
      ! grep -R -Eq 'needs\.(changes|check|plan)|inputs\.publish|publish: true' \
        .github/workflows
      grep -qF 'attest-software-bill-of-materials.yml' .github/workflows/build.yml
      grep -qF 'attest-software-bill-of-materials.yml' lib/installer-application.nix
      grep -qF 'attest-software-bill-of-materials.yml' .github/workflows/release.yml
      grep -qF 'toolset: workflow-release' .github/workflows/release.yml
      grep -qF 'cachix/install-nix-action@13d8dd58da0234aa297dedd986986ccb8e7f3e24' \
        .github/actions/setup-nix/action.yml
      grep -qF 'cachix/cachix-action@5f2d7c5294214f71b873db4b969586b980625e71' \
        .github/actions/setup-nix/action.yml
      grep -qF 'nix build --accept-flake-config' \
        .github/actions/setup-nix/action.yml
      grep -qF -- '--out-link /tmp/purplefin-workflow-toolset' \
        .github/actions/setup-nix/action.yml
      grep -qF 'nix run --accept-flake-config .#github-actions-secrets' \
        .github/actions/setup-nix/action.yml
      grep -qF 'authToken: ''${{ env.CACHIX_AUTH_TOKEN }}' \
        .github/actions/setup-nix/action.yml
      [[ "$(grep -R -h -oF 'secrets.CACHIX_AUTH_TOKEN' .github | wc -l)" == 1 ]]
      [[ "$(grep -R -h -oF 'secrets.MERGE_QUEUE_TOKEN' .github | wc -l)" == 4 ]]
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
      grep -qF -- '--build-context installer-rootfs=installer/rootfs' \
        lib/installer-application.nix
      grep -qF 'RUN --mount=from=installer-rootfs,target=/run/installer-rootfs' \
        installer/Containerfile
      grep -qF '@@INSTALLER_PAYLOAD_SOURCE_REF@@' \
        installer/rootfs/usr/share/anaconda/interactive-defaults.ks
      grep -qF 'checks.''${system} =' modules/outputs.nix
      grep -qF 'repositoryChecks' modules/outputs.nix

      for workflow in .github/workflows/*.yml; do
        yq -e 'has("jobs") and (.jobs | length > 0)' "''${workflow}" >/dev/null
      done

      for verifier in lib/installer-application.nix .github/workflows/release.yml; do
        [[ "$(grep -cF 'gh attestation verify "oci://' "''${verifier}")" == \
          "$(grep -cF -- '--bundle-from-oci' "''${verifier}")" ]]
      done
      grep -qF '"''${gh_command}" attestation verify' bootc/builder/sbom.sh
      grep -qF -- '--bundle-from-oci' bootc/builder/sbom.sh

      actionlint -color .github/workflows/*.yml
      zizmor --offline --no-config --collect=all .github
    '';
  };

  nix = mkSourceCheck {
    name = "nix-checks";
    source = nixSource;
    tools = [pkgs.statix];
    commands = ''
      statix check .
    '';
  };
}
