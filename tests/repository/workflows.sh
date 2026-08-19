#!/usr/bin/env bash
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
  grep -qF 'nix run .#trusted-update' ".github/workflows/${updater}"
done
[[ "$(grep -cF 'purplefin-trusted-update' .github/workflows/release.yml)" == 2 ]]
[[ "$(grep -cF 'SOURCE_SHA: ${{ steps.source.outputs.source_sha }}' .github/workflows/release.yml)" == 2 ]]
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
! grep -R -Eq 'needs\.(changes|check|plan)|inputs\.publish|publish: true' .github/workflows
grep -qF 'attest-software-bill-of-materials.yml' .github/workflows/build.yml
grep -qF 'attest-software-bill-of-materials.yml' automation/installer/build.sh
grep -qF 'attest-software-bill-of-materials.yml' .github/workflows/release.yml
grep -qF 'toolset: workflow-release' .github/workflows/release.yml
grep -qF 'cachix/install-nix-action@13d8dd58da0234aa297dedd986986ccb8e7f3e24' \
  .github/actions/setup-nix/action.yml
grep -qF 'cachix/cachix-action@5f2d7c5294214f71b873db4b969586b980625e71' \
  .github/actions/setup-nix/action.yml
grep -qF 'nix build --accept-flake-config' .github/actions/setup-nix/action.yml
grep -qF -- '--out-link /tmp/purplefin-workflow-toolset' .github/actions/setup-nix/action.yml
grep -qF 'nix run --accept-flake-config .#github-actions-secrets' .github/actions/setup-nix/action.yml
grep -qF 'authToken: ${{ env.CACHIX_AUTH_TOKEN }}' .github/actions/setup-nix/action.yml
[[ "$(grep -R -h -oF 'secrets.CACHIX_AUTH_TOKEN' .github | wc -l)" == 1 ]]
[[ "$(grep -R -h -oF 'secrets.MERGE_QUEUE_TOKEN' .github | wc -l)" == 5 ]]
! grep -R -qF 'token: ${{ secrets.MERGE_QUEUE_TOKEN' .github
grep -qF 'GH_TOKEN: ${{ env.MERGE_QUEUE_TOKEN || github.token }}' \
  .github/workflows/queue-dependabot.yml
! grep -qF 'nix profile add' .github/actions/setup-nix/action.yml
! grep -R -qF 'DeterminateSystems/determinate-nix-action' .github
grep -qF -- '--build-context purplefin-generated=' .github/workflows/build-profile.yml
grep -qF 'RUN --mount=type=bind,from=purplefin-generated,source=.,target=/run/purplefin-generated' \
  bootc/Containerfile
grep -qF 'containerfile=./bootc/Containerfile' .github/workflows/build-profile.yml
grep -qF 'purplefin-installer-build' .github/actions/build-installer/action.yml
grep -qF -- '--build-context installer-rootfs=installer/rootfs' automation/installer/build.sh
grep -qF 'RUN --mount=from=installer-rootfs,target=/run/installer-rootfs' installer/Containerfile
grep -qF '@@INSTALLER_PAYLOAD_SOURCE_REF@@' \
  installer/rootfs/usr/share/anaconda/interactive-defaults.ks
grep -qF 'checks.${system} =' modules/outputs.nix
grep -qF 'repositoryChecks' modules/outputs.nix

for workflow in .github/workflows/*.yml; do
  yq -e 'has("jobs") and (.jobs | length > 0)' "${workflow}" >/dev/null
done

for verifier in automation/installer/build.sh .github/workflows/release.yml; do
  [[ "$(grep -cF 'gh attestation verify "oci://' "${verifier}")" == \
    "$(grep -cF -- '--bundle-from-oci' "${verifier}")" ]]
done
grep -qF '"${gh_command}" attestation verify' bootc/builder/sbom.sh
grep -qF -- '--bundle-from-oci' bootc/builder/sbom.sh

actionlint -color .github/workflows/*.yml
zizmor --offline --no-config --collect=all .github
