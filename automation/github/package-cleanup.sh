#!/usr/bin/env bash
set -euo pipefail

: "${DRY_RUN:=true}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GITHUB_REPOSITORY_OWNER:?GITHUB_REPOSITORY_OWNER is required}"
: "${PURPLEFIN_GENERATED_ROOT:?PURPLEFIN_GENERATED_ROOT is required}"

owner="${GITHUB_REPOSITORY_OWNER}"
package="${GITHUB_REPOSITORY#*/}"
obsolete_tags='["dale-cosmic","development-desktop-x86_64","support-lenovo-generic"]'
active_cache_tags="$({
	jq -c '[.[] | "\(.profile)-\(.build_input)"]' \
		"${PURPLEFIN_GENERATED_ROOT}/bootc/generated/image-matrix.json"
})"

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

cache_package="${package}-sbom-cache"
if ! cache_versions="$({
	gh api --paginate "/users/${owner}/packages/container/${cache_package}/versions?per_page=100" --slurp 2>/dev/null
})"; then
	echo "Cache package ${cache_package} does not exist yet"
	exit 0
fi
jq -c --argjson active "${active_cache_tags}" '
  add[] | . as $version | (.metadata.container.tags // []) as $tags |
  select(($tags | length) == 0 or all($tags[]; . as $tag |
    (any($active[]; . as $prefix | $tag | startswith($prefix + "-")) | not))) |
  {id: $version.id, tags: $tags}
' <<<"${cache_versions}" |
	while IFS= read -r candidate; do
		version_id="$(jq -r '.id' <<<"${candidate}")"
		tags="$(jq -r '.tags | if length == 0 then "untagged" else join(", ") end' <<<"${candidate}")"
		echo "Obsolete ${cache_package} version ${version_id}: ${tags}"
		delete_version "${cache_package}" "${version_id}"
	done
