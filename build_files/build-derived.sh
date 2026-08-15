#!/usr/bin/env bash
set -euo pipefail

build_root="${PURPLEFIN_BUILD_ROOT:-/tmp/purplefin-build}"
profile="${1:?usage: build-derived.sh PROFILE PARENT_PROFILE}"
parent_profile="${2:?usage: build-derived.sh PROFILE PARENT_PROFILE}"
profile_catalog="${build_root}/profile-catalog.json"
module_root="${build_root}/modules"
valid_name='^[a-z0-9._-]+$'

[[ "${profile}" =~ ${valid_name} ]] || { echo "Invalid build profile: ${profile}" >&2; exit 2; }
[[ "${parent_profile}" =~ ${valid_name} ]] || { echo "Invalid parent profile: ${parent_profile}" >&2; exit 2; }
[[ "${profile}" != "${parent_profile}" ]] || { echo 'A derived profile cannot be its own parent' >&2; exit 2; }

[[ -f "${profile_catalog}" ]] || { echo "Missing generated profile catalog: ${profile_catalog}" >&2; exit 2; }
jq -e --arg profile "${profile}" '.profiles[$profile]' "${profile_catalog}" >/dev/null || {
	echo "Unknown build profile: ${profile}" >&2
	exit 2
}
catalog_parent="$(jq -er --arg profile "${profile}" '.profiles[$profile].parent' "${profile_catalog}")"
[[ "${catalog_parent}" == "${parent_profile}" ]] || { echo "Profile ${profile} does not inherit ${parent_profile}" >&2; exit 2; }
mapfile -t target_modules < <(jq -er --arg profile "${profile}" '.profiles[$profile].modules[]' "${profile_catalog}")
mapfile -t delta_modules < <(jq -er --arg profile "${profile}" '.profiles[$profile].deltaModules[]' "${profile_catalog}")
(( ${#delta_modules[@]} > 0 )) || { echo "Profile ${profile} has no generated module delta" >&2; exit 2; }

declare -A applied_modules=()
hardware_delta_count=0
for module in "${delta_modules[@]}"; do
	[[ "${module}" =~ ${valid_name} && "${module}" != base ]] || {
		echo "Invalid derived module in ${profile}: ${module}" >&2
		exit 2
	}
	if [[ "${module}" == hardware-* ]]; then
		((hardware_delta_count += 1))
	fi
	[[ -z "${applied_modules[${module}]:-}" ]] || { echo "Duplicate module in ${profile}: ${module}" >&2; exit 2; }
	module_script="${module_root}/${module}.sh"
	[[ -x "${module_script}" ]] || { echo "Unknown module in ${profile}: ${module}" >&2; exit 2; }
	applied_modules["${module}"]=1
done
(( hardware_delta_count <= 1 )) || { echo "Profile ${profile} adds multiple hardware modules" >&2; exit 2; }

if [[ "${PURPLEFIN_DERIVED_DRY_RUN:-false}" == true ]]; then
	printf '%s\n' "${delta_modules[@]}"
	exit 0
fi

if (( hardware_delta_count == 1 )); then
	# shellcheck source=/tmp/purplefin-build/profiles/lib/authselect-features.sh
	source "${build_root}/profiles/lib/authselect-features.sh"
	purplefin_authselect_reset
fi

for module in "${delta_modules[@]}"; do
	echo ":: Applying Purplefin derived module: ${module}"
	"${module_root}/${module}.sh"
done

if (( hardware_delta_count == 1 )); then
	purplefin_authselect_finalize
fi

# shellcheck source=/tmp/purplefin-build/lib/finalize-profile.sh
source "${build_root}/lib/finalize-profile.sh"
purplefin_update_independently_managed_rpms "${build_root}"
purplefin_finalize_profile "${profile}" "${target_modules[@]}"
