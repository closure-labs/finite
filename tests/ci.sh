#!/usr/bin/env bash
set -euo pipefail

just check

treefmt --fail-on-change

mapfile -d '' shell_files < <(
	find bootc ci installer tests \
		-type f -name '*.sh' -print0
)
shellcheck --external-sources --source-path=SCRIPTDIR "${shell_files[@]}"
tests/text-style.sh
tests/changed-component.sh
tests/trusted-update-validation.sh

jq -e '
  .target == "branch" and
  .enforcement == "active" and
  any(.rules[]; .type == "merge_queue") and
  any(
    .rules[];
    .type == "required_status_checks" and
    any(.parameters.required_status_checks[]; .context == "CI gate" and .integration_id == 15368)
  )
' ci/github/main-merge-queue.json >/dev/null
jq -e '
  .target == "branch" and
  .enforcement == "active" and
  all(.rules[]; .type != "merge_queue") and
  any(
    .rules[];
    .type == "required_status_checks" and
    .parameters.strict_required_status_checks_policy == true and
    any(.parameters.required_status_checks[]; .context == "CI gate" and .integration_id == 15368)
  )
' ci/github/main-protection.json >/dev/null
grep -qF '  merge_group:' .github/workflows/build.yml
grep -qF '    name: CI gate' .github/workflows/build.yml
grep -qF '    name: Classify expensive validations' .github/workflows/build.yml
grep -qF '    name: Validate installer' .github/workflows/build.yml
grep -qF "images: \${{ steps.filter.outputs.images }}" .github/workflows/build.yml
grep -qF 'ci/changed-component.sh images' .github/workflows/build.yml
grep -qF 'ci/changed-component.sh installer' .github/workflows/build.yml
grep -qF "if: needs.changes.outputs.images == 'true'" .github/workflows/build.yml
grep -qF "require_selected_result plan \"\${IMAGES_SELECTED}\"" .github/workflows/build.yml
grep -qF 'require_selected_result installer-candidate' .github/workflows/build.yml
grep -qF "FORCE_REBUILD: \${{ github.event_name == 'workflow_dispatch' && inputs.force }}" .github/workflows/build.yml
grep -qF "(github.event_name == 'workflow_dispatch' && inputs.validate_only)" .github/workflows/build.yml
grep -qF "VALIDATE_ONLY: \${{ github.event_name ==" .github/workflows/build.yml
grep -qF 'name: Queue Dependabot updates' .github/workflows/queue-dependabot.yml
grep -qF 'select(.user.login == "dependabot[bot]")' .github/workflows/queue-dependabot.yml
grep -qF "select(.head.repo.full_name == \$repository)" .github/workflows/queue-dependabot.yml
if grep -qF '  - package-ecosystem: nix' .github/dependabot.yml; then
	echo 'Nix inputs must be updated by Determinate, not Dependabot' >&2
	exit 1
fi
grep -qF 'name: Update Nix flake inputs' .github/workflows/update-flake-lock.yml
grep -qF 'DeterminateSystems/update-flake-lock@834c491b2ece4de0bbd00d85214bb5e83b4da5c6' .github/workflows/update-flake-lock.yml
grep -qF 'branch: automation/weekly-flake-input-refresh' .github/workflows/update-flake-lock.yml
grep -qF 'EXPECTED_AUTHOR:' .github/workflows/update-flake-lock.yml
grep -qF 'name: Update Image Builder CLI digest' .github/workflows/update-image-builder.yml
grep -qF 'IMAGE_BUILDER_TAG: ghcr.io/osbuild/image-builder-cli:latest' .github/workflows/update-image-builder.yml
grep -qF 'EXPECTED_AUTHOR:' .github/workflows/update-image-builder.yml
grep -qF -- '--event pull_request' ci/validate-trusted-update.sh
grep -qF 'dispatch_and_wait build.yml -f validate_only=true' ci/validate-trusted-update.sh
grep -qF '.headRepository.nameWithOwner' ci/validate-trusted-update.sh
installer_action=.github/actions/build-installer/action.yml
if grep -qF -- '--blueprint' "${installer_action}"; then
	echo 'bootc-generic-iso does not support Blueprint customizations' >&2
	exit 1
fi
grep -qF -- '--build-context installer-overlay=installer/overlay' "${installer_action}"
grep -qF "sudo podman tag \"\${PAYLOAD_REF}\" \"\${PAYLOAD_EMBED_REF}\"" "${installer_action}"
grep -qF -- "--bootc-installer-payload-ref \"\${PAYLOAD_EMBED_REF}\"" "${installer_action}"
grep -qF "sudo chown -R \"\$(id -u):\$(id -g)\" output" "${installer_action}"
grep -qF -- "--cache-from \"\${CACHE_REF}\" --cache-ttl 336h" "${installer_action}"
grep -qF "cache_ref=\"\${IMAGE_REF}-installer-cache\"" "${installer_action}"
grep -qF "gh attestation verify \"oci://\${payload_ref}\"" "${installer_action}"
grep -qF "installer_image_id=\"\${installer_image_id#sha256:}\"" "${installer_action}"
grep -qF "installer_image_id=\"sha256:\${installer_image_id}\"" "${installer_action}"
grep -qF 'output/installer-manifest.json' "${installer_action}"
grep -qF 'name: Upload installer diagnostics' "${installer_action}"
grep -qF 'name: Summarize profile build' .github/workflows/build-profile.yml
grep -qF 'steps.build.outputs.cache_available' .github/workflows/build-profile.yml
grep -qF "gh attestation verify \"oci://\${immutable_ref}\"" .github/workflows/release.yml
grep -qF -- '--predicate-type https://spdx.dev/Document/v2.3' .github/workflows/release.yml
grep -qF 'RUN --mount=from=installer-overlay,target=/run/installer-overlay' installer/Containerfile
grep -qF 'cp -a /run/installer-overlay/. /' installer/Containerfile
grep -qF '@@INSTALLER_PAYLOAD_SOURCE_REF@@' installer/overlay/usr/share/anaconda/interactive-defaults.ks
grep -qF '@@INSTALLER_PAYLOAD_TARGET_REF@@' installer/overlay/usr/share/anaconda/interactive-defaults.ks

actionlint -color
zizmor --offline .github
