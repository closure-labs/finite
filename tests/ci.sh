#!/usr/bin/env bash
set -euo pipefail

just check

alejandra --check .
deadnix --fail .

mapfile -d '' shell_files < <(
	find bootc installer tests \
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
grep -qF -- '-f validate_only=true' .github/workflows/update-flake-lock.yml

actionlint -color
zizmor --offline .github/workflows
