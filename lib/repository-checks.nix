{
  applications,
  architecture,
  generated,
  inputs,
  pkgs,
  repositoryToolchain,
}: let
  mkSourceCheck = name: commands:
    pkgs.runCommand "purplefin-${name}" {
      nativeBuildInputs =
        repositoryToolchain
        ++ [
          applications.classifyChanges
          applications.releaseNotes
          applications.trustedUpdate
        ];
    } ''
      export HOME="$TMPDIR/home"
      mkdir -p "$HOME" source
      cp -R ${inputs.self}/. source/
      chmod -R u+w source
      cd source
      export PURPLEFIN_GENERATED_ROOT=${generated}
      export PURPLEFIN_HERMETIC_CHECK=true
      export PURPLEFIN_SOURCE_ROOT="$PWD"
      ${commands}
      touch "$out"
    '';
in {
  shell = mkSourceCheck "shell-checks" ''
    mapfile -d $'\0' shell_files < <(
      find automation bootc installer modules tests \
        -type f -name '*.sh' -print0
    )
    bash -n "''${shell_files[@]}"
    shellcheck --external-sources --source-path=SCRIPTDIR "''${shell_files[@]}"
  '';

  repository = mkSourceCheck "repository-contracts" ''
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
  '';

  documentation = mkSourceCheck "documentation-checks" ''
    bash tests/repository/text-style.sh
    bash tests/repository/markdown-links.sh
  '';

  automation = mkSourceCheck "automation-checks" ''
    bash tests/automation/classify-changes.sh
    bash tests/automation/trusted-update.sh
  '';

  bootc = mkSourceCheck "bootc-checks" ''
    bash tests/bootc/derived-profile.sh
    bash tests/bootc/plan.sh
    bash tests/bootc/reuse-image.sh
  '';

  aspects = mkSourceCheck "aspect-contracts" ''
    bash modules/aspects/base/tests/contracts.sh
    bash modules/aspects/capabilities/devops/tests/contracts.sh
    bash modules/aspects/roles/support/tests/contracts.sh
    bash modules/aspects/hardware/dell-xps-9350-intel/tests/lid-auth.sh
    bash modules/aspects/hardware/dell-xps-9350-intel/tests/policies.sh
  '';

  release = mkSourceCheck "release-contracts" ''
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

  workflows = mkSourceCheck "workflow-checks" ''
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

    grep -qF 'nix flake check --print-build-logs' .github/workflows/build.yml
    grep -qF 'nix run .#trusted-update' .github/workflows/update-flake-lock.yml
    grep -qF 'nix run .#trusted-update' .github/workflows/update-image-builder.yml
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
}
