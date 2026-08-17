#!/usr/bin/env bash
set -euo pipefail

generated_root="${PURPLEFIN_GENERATED_ROOT:?PURPLEFIN_GENERATED_ROOT is required}"

treefmt --fail-on-change

mapfile -d '' shell_files < <(
	find automation bootc installer modules tests \
		-type f -name '*.sh' -print0
)
bash -n "${shell_files[@]}"
shellcheck --external-sources --source-path=SCRIPTDIR "${shell_files[@]}"

bash tests/repository/contracts.sh
bash tests/repository/text-style.sh
bash tests/repository/markdown-links.sh
bash tests/automation/classify-changes.sh
bash tests/automation/trusted-update.sh
bash tests/bootc/derived-profile.sh
bash tests/bootc/plan.sh
bash tests/bootc/reuse-image.sh
bash modules/aspects/base/tests/contracts.sh
bash modules/aspects/capabilities/devops/tests/contracts.sh
bash modules/aspects/roles/support/tests/contracts.sh
bash modules/aspects/hardware/dell-xps-9350-intel/tests/lid-auth.sh
bash modules/aspects/hardware/dell-xps-9350-intel/tests/policies.sh

latest_changelog_version="$({
	sed -nE 's/^## \[([0-9]+\.[0-9]+\.[0-9]+)\] - [0-9]{4}-[0-9]{2}-[0-9]{2}$/\1/p' \
		CHANGELOG.md | head -n 1
})"
[[ -n "${latest_changelog_version}" ]]
release_notes="$(bash automation/release/notes.sh "${latest_changelog_version}" CHANGELOG.md)"
for heading in Added Changed Fixed Security; do
	grep -qF "### ${heading}" <<<"${release_notes}"
done
if grep -qF '[Unreleased]:' <<<"${release_notes}"; then
	echo 'release notes unexpectedly contain the Unreleased link target' >&2
	exit 1
fi
if [[ "$(<VERSION)" != *-dev.* ]]; then
	[[ "$(<VERSION)" == "${latest_changelog_version}" ]]
fi

jq -e '
  .target == "branch" and
  .enforcement == "active" and
  any(.rules[]; .type == "merge_queue") and
  any(.rules[]; .type == "required_status_checks" and
    any(.parameters.required_status_checks[]; .context == "CI gate" and .integration_id == 15368))
' automation/github/policies/main-merge-queue.json >/dev/null
jq -e '
  .target == "branch" and
  .enforcement == "active" and
  all(.rules[]; .type != "merge_queue") and
  any(.rules[]; .type == "required_status_checks" and
    .parameters.strict_required_status_checks_policy == true and
    any(.parameters.required_status_checks[]; .context == "CI gate" and .integration_id == 15368))
' automation/github/policies/main-protection.json >/dev/null

grep -qF 'nix flake check --print-build-logs' .github/workflows/build.yml
grep -qF 'nix run .#trusted-update' .github/workflows/update-flake-lock.yml
grep -qF 'nix run .#trusted-update' .github/workflows/update-image-builder.yml
grep -qF 'nix run .#export-artifacts -- .' .github/workflows/build-profile.yml
grep -qF 'containerfile=./bootc/Containerfile' .github/workflows/build-profile.yml
grep -qF -- '--build-context installer-rootfs=installer/rootfs' .github/actions/build-installer/action.yml
grep -qF 'RUN --mount=from=installer-rootfs,target=/run/installer-rootfs' installer/Containerfile
grep -qF '@@INSTALLER_PAYLOAD_SOURCE_REF@@' installer/rootfs/usr/share/anaconda/interactive-defaults.ks
grep -qF 'repository = repositoryCheck;' modules/outputs.nix

actionlint -color .github/workflows/*.yml
zizmor --offline --no-config --collect=all .github

test -f "${generated_root}/bootc/generated/profile-catalog.json"
