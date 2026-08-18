{
  applications,
  architecture,
  generated,
  lib,
  pkgs,
  repositoryToolchain,
}: let
  root = ../.;
  inherit (lib) fileset;
  sourceFor = selected:
    fileset.toSource {
      inherit root;
      fileset = fileset.unions selected;
    };
  shellSource = sourceFor [
    ../automation
    ../bootc
    ../installer
    ../modules
    ../tests
  ];
  repositorySource = sourceFor [
    ../VERSION
    ../bootc/Containerfile
    ../bootc/Containerfile.derived
    ../bootc/builder
    ../modules/aspects
    ../npins
    ../secretspec.toml
    ../tests/repository/contracts.sh
  ];
  documentationSource = sourceFor [
    root
  ];
  automationSource = sourceFor [
    ../automation/github
    ../tests/automation
  ];
  bootcSource = sourceFor [
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
    ../npins
    ../secretspec.toml
  ];
  workflowSource = sourceFor [
    ../.github
    ../automation/github/policies
    ../bootc/Containerfile
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
      nativeBuildInputs =
        repositoryToolchain
        ++ tools;
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
    commands = ''
      mapfile -d $'\0' shell_files < <(
        find automation bootc installer modules tests \
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
    commands = ''
      jq -e '
        .version == 8 and (
          .pins["bluefin-stable"] as $pin |
          $pin.type == "Container" and
          $pin.image_name == "ghcr.io/projectbluefin/bluefin" and
          $pin.image_tag == "stable" and
          $pin.arch == "amd64" and
          ($pin.image_digest | test("^sha256:[0-9a-f]{64}$")) and
          ($pin.hash | test("^sha256-[A-Za-z0-9+/]{43}=$"))
        )
      ' npins/sources.json >/dev/null
      secretspec schema --file secretspec.toml --profile local-cache |
        jq -e '.required == ["CACHIX_AUTH_TOKEN"]' >/dev/null
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
    commands = ''
      bash tests/repository/text-style.sh
      bash tests/repository/markdown-links.sh
    '';
  };

  automation = mkSourceCheck {
    name = "automation-checks";
    source = automationSource;
    tools = [applications.classifyChanges applications.classifyCi applications.trustedUpdate];
    commands = ''
      bash tests/automation/classify-changes.sh
      bash tests/automation/classify-ci.sh
      bash tests/automation/trusted-update.sh
    '';
  };

  bootc = mkSourceCheck {
    name = "bootc-checks";
    source = bootcSource;
    generatedRoot = generated;
    commands = ''
      bash tests/bootc/derived-profile.sh
      bash tests/bootc/plan.sh
      bash tests/bootc/reuse-image.sh
    '';
  };

  aspects = mkSourceCheck {
    name = "aspect-contracts";
    source = aspectsSource;
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
    tools = [applications.releaseNotes];
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
      grep -qF 'nix run .#update-bluefin' .github/workflows/update-bluefin.yml
      grep -qF 'nix run .#load-bluefin' .github/workflows/build-profile.yml
      grep -qF 'nix run .#ci-plan' .github/workflows/build.yml
      grep -qF 'nix run .#classify-ci' .github/workflows/build.yml
      grep -qF 'cachix/install-nix-action@13d8dd58da0234aa297dedd986986ccb8e7f3e24' \
        .github/actions/setup-nix/action.yml
      grep -qF 'cachix/cachix-action@5f2d7c5294214f71b873db4b969586b980625e71' \
        .github/actions/setup-nix/action.yml
      ! grep -R -qF 'DeterminateSystems/determinate-nix-action' .github
      grep -qF 'nix run .#export-artifacts -- .' .github/workflows/build-profile.yml
      grep -qF 'containerfile=./bootc/Containerfile' .github/workflows/build-profile.yml
      grep -qF 'nix run .#installer-build' .github/actions/build-installer/action.yml
      grep -qF -- '--build-context installer-rootfs=installer/rootfs' \
        lib/installer-application.nix
      grep -qF 'RUN --mount=from=installer-rootfs,target=/run/installer-rootfs' \
        installer/Containerfile
      grep -qF '@@INSTALLER_PAYLOAD_SOURCE_REF@@' \
        installer/rootfs/usr/share/anaconda/interactive-defaults.ks
      grep -qF 'checks.''${system} =' modules/outputs.nix
      grep -qF 'repositoryChecks' modules/outputs.nix

      for verifier in lib/installer-application.nix .github/workflows/release.yml; do
        [[ "$(grep -cF 'gh attestation verify "oci://' "''${verifier}")" == \
          "$(grep -cF -- '--bundle-from-oci' "''${verifier}")" ]]
      done

      actionlint -color .github/workflows/*.yml
      zizmor --offline --no-config --collect=all .github
    '';
  };
}
