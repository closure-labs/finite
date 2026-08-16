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
grep -qF "FORCE_REBUILD: \${{ github.event_name == 'merge_group'" .github/workflows/build.yml
grep -qF "(github.event_name == 'workflow_dispatch' && inputs.validate_only)" .github/workflows/build.yml
grep -qF "VALIDATE_ONLY: \${{ github.event_name ==" .github/workflows/build.yml
grep -qF 'name: Queue trusted update bots' .github/workflows/queue-trusted-updates.yml
grep -qF "GH_TOKEN: \${{ secrets.MERGE_QUEUE_TOKEN || github.token }}" .github/workflows/queue-trusted-updates.yml
grep -qF "token: \${{ secrets.MERGE_QUEUE_TOKEN || github.token }}" .github/workflows/update-flake-lock.yml
grep -qF 'run: ci/validate-trusted-update.sh' .github/workflows/update-flake-lock.yml
grep -qF 'name: Update Image Builder CLI digest' .github/workflows/update-image-builder.yml
grep -qF 'IMAGE_BUILDER_TAG: ghcr.io/osbuild/image-builder-cli:latest' .github/workflows/update-image-builder.yml
grep -qF 'VALIDATE_INSTALLER: "true"' .github/workflows/update-image-builder.yml
grep -qF 'dispatch_and_wait build.yml -f validate_only=true' ci/validate-trusted-update.sh
grep -qF 'dispatch_and_wait build-installer.yml -f image-tag=base-generic-x86_64' ci/validate-trusted-update.sh

actionlint -color
zizmor --offline .github/workflows
