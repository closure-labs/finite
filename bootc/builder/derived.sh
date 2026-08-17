#!/usr/bin/env bash
set -euo pipefail

build_root="${PURPLEFIN_BUILD_ROOT:-/tmp/purplefin-build}"
generated_root="${PURPLEFIN_GENERATED_ROOT:-${build_root}}"
profile="${1:?usage: derived.sh PROFILE PARENT_PROFILE}"
parent_profile="${2:?usage: derived.sh PROFILE PARENT_PROFILE}"
profile_catalog="${generated_root}/bootc/generated/profile-catalog.json"
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
mapfile -t delta_steps < <(
	jq -er --arg profile "${profile}" '.profiles[$profile].deltaBuildSteps[] | [.name, .script] | @tsv' "${profile_catalog}"
)
((${#delta_steps[@]} > 0)) || { echo "Profile ${profile} has no generated build-step delta" >&2; exit 2; }

declare -A applied_steps=()
delta_names=()
hardware_delta_count=0
for build_step in "${delta_steps[@]}"; do
	IFS=$'\t' read -r step_name step_script <<<"${build_step}"
	[[ "${step_name}" =~ ${valid_name} && "${step_name}" != base ]] || {
		echo "Invalid derived build step in ${profile}: ${step_name}" >&2
		exit 2
	}
	[[ "${step_script}" != /* && "${step_script}" != *..* ]] || { echo "Unsafe build-step path in ${profile}: ${step_script}" >&2; exit 2; }
	if [[ "${step_name}" == hardware-* ]]; then
		((hardware_delta_count += 1))
	fi
	[[ -z "${applied_steps[${step_name}]:-}" ]] || { echo "Duplicate build step in ${profile}: ${step_name}" >&2; exit 2; }
	[[ -x "${build_root}/${step_script}" ]] || { echo "Missing build step in ${profile}: ${step_script}" >&2; exit 2; }
	applied_steps["${step_name}"]="${step_script}"
	delta_names+=("${step_name}")
done
((hardware_delta_count <= 1)) || { echo "Profile ${profile} adds multiple hardware aspects" >&2; exit 2; }

if [[ "${PURPLEFIN_DERIVED_DRY_RUN:-false}" == true ]]; then
	printf '%s\n' "${delta_names[@]}"
	exit 0
fi

if ((hardware_delta_count == 1)); then
	# shellcheck source=/tmp/purplefin-build/bootc/builder/lib/authselect-features.sh
	source "${build_root}/bootc/builder/lib/authselect-features.sh"
	purplefin_authselect_reset
fi

for build_step in "${delta_steps[@]}"; do
	IFS=$'\t' read -r step_name step_script <<<"${build_step}"
	echo ":: Applying Purplefin derived aspect: ${step_name}"
	"${build_root}/${step_script}"
done

if ((hardware_delta_count == 1)); then
	purplefin_authselect_finalize
fi

# shellcheck source=/tmp/purplefin-build/bootc/builder/lib/finalize-profile.sh
source "${build_root}/bootc/builder/lib/finalize-profile.sh"
purplefin_update_independently_managed_rpms "${build_root}"
purplefin_finalize_profile "${profile}" "${target_modules[@]}"
