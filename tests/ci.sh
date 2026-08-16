#!/usr/bin/env bash
set -euo pipefail

just check

alejandra --check .
deadnix --fail .

mapfile -d '' shell_files < <(
	find bootc ci installer tests \
		-type f -name '*.sh' -print0
)
shellcheck --external-sources --source-path=SCRIPTDIR "${shell_files[@]}"
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
grep -qF "FORCE_REBUILD: \${{ github.event_name == 'workflow_dispatch' && inputs.force }}" .github/workflows/build.yml
grep -qF "(github.event_name == 'workflow_dispatch' && inputs.validate_only)" .github/workflows/build.yml
grep -qF "VALIDATE_ONLY: \${{ github.event_name ==" .github/workflows/build.yml
grep -qF 'name: Queue Dependabot updates' .github/workflows/queue-dependabot.yml
grep -qF 'select(.user.login == "dependabot[bot]")' .github/workflows/queue-dependabot.yml
grep -qF "select(.head.repo.full_name == \$repository)" .github/workflows/queue-dependabot.yml
grep -qF "token: \${{ secrets.MERGE_QUEUE_TOKEN || github.token }}" .github/workflows/update-flake-lock.yml
grep -qF 'run: ci/validate-trusted-update.sh' .github/workflows/update-flake-lock.yml
grep -qF 'name: Update Image Builder CLI digest' .github/workflows/update-image-builder.yml
grep -qF 'IMAGE_BUILDER_TAG: ghcr.io/osbuild/image-builder-cli:latest' .github/workflows/update-image-builder.yml
grep -qF 'VALIDATE_INSTALLER: "true"' .github/workflows/update-image-builder.yml
grep -qF -- '--event pull_request' ci/validate-trusted-update.sh
grep -qF 'dispatch_and_wait build.yml -f validate_only=true' ci/validate-trusted-update.sh
grep -qF 'dispatch_and_wait build-installer.yml -f image-tag=base-generic-x86_64' ci/validate-trusted-update.sh
if grep -qF -- '--blueprint' .github/workflows/build-installer.yml; then
	echo 'bootc-generic-iso does not support Blueprint customizations' >&2
	exit 1
fi
grep -qF -- '--build-context installer-overlay=installer/overlay' .github/workflows/build-installer.yml
grep -qF 'sudo podman tag "${PAYLOAD_REF}" "${PAYLOAD_EMBED_REF}"' .github/workflows/build-installer.yml
grep -qF -- '--bootc-installer-payload-ref "${PAYLOAD_EMBED_REF}"' .github/workflows/build-installer.yml
grep -qF 'RUN --mount=from=installer-overlay,target=/run/installer-overlay' installer/Containerfile
grep -qF 'cp -a /run/installer-overlay/. /' installer/Containerfile
grep -qF '@@INSTALLER_PAYLOAD_SOURCE_REF@@' installer/overlay/usr/share/anaconda/interactive-defaults.ks
grep -qF '@@INSTALLER_PAYLOAD_TARGET_REF@@' installer/overlay/usr/share/anaconda/interactive-defaults.ks

actionlint -color
zizmor --offline .github/workflows
