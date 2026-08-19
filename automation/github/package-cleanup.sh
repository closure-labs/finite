#!/usr/bin/env bash
set -euo pipefail

: "${DRY_RUN:=true}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GITHUB_REPOSITORY_OWNER:?GITHUB_REPOSITORY_OWNER is required}"

owner="${GITHUB_REPOSITORY_OWNER}"
package="${GITHUB_REPOSITORY#*/}"
obsolete_tags='["dale-cosmic","development-desktop-x86_64","support-lenovo-generic"]'

delete_version() {
	local package_name="$1"
	local version_id="$2"
	if [[ "${DRY_RUN}" != true ]]; then
		gh api --method DELETE \
			"/users/${owner}/packages/container/${package_name}/versions/${version_id}"
	fi
}

versions="$({
	gh api --paginate "/users/${owner}/packages/container/${package}/versions?per_page=100" --slurp
})"
jq -c --argjson obsolete "${obsolete_tags}" '
  add[] | . as $version | (.metadata.container.tags // []) as $tags |
  select(($tags | length) > 0) |
  select(all($tags[]; $obsolete | index(.) != null)) |
  {id: $version.id, tags: $tags}
' <<<"${versions}" |
	while IFS= read -r candidate; do
		version_id="$(jq -r '.id' <<<"${candidate}")"
		echo "Obsolete package version ${version_id}: $(jq -r '.tags | join(", ")' <<<"${candidate}")"
		delete_version "${package}" "${version_id}"
	done
