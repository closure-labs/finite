#!/usr/bin/env bash
set -euo pipefail

build_root="${PURPLEFIN_BUILD_ROOT:-/tmp/purplefin-build}"
profile="${1:?usage: build-derived.sh PROFILE PARENT_PROFILE}"
parent_profile="${2:?usage: build-derived.sh PROFILE PARENT_PROFILE}"
profile_definition="${build_root}/profiles/profiles/${profile}.conf"
parent_definition="${build_root}/profiles/profiles/${parent_profile}.conf"
module_root="${build_root}/modules"
valid_name='^[a-z0-9._-]+$'

[[ "${profile}" =~ ${valid_name} ]] || { echo "Invalid build profile: ${profile}" >&2; exit 2; }
[[ "${parent_profile}" =~ ${valid_name} ]] || { echo "Invalid parent profile: ${parent_profile}" >&2; exit 2; }
[[ "${profile}" != "${parent_profile}" ]] || { echo 'A derived profile cannot be its own parent' >&2; exit 2; }

load_profile_modules() {
	local definition="$1"
	local expected_name="$2"
	local -n output_modules="$3"
	local profile_name=
	local -a modules=()

	[[ -f "${definition}" ]] || { echo "Unknown build profile: ${expected_name}" >&2; exit 2; }
	# shellcheck source=/dev/null
	source "${definition}"
	[[ "${profile_name:-}" == "${expected_name}" ]] || { echo "Invalid profile definition: ${definition}" >&2; exit 2; }
	declare -p modules >/dev/null 2>&1 || { echo "Profile ${expected_name} does not define modules" >&2; exit 2; }
	# shellcheck disable=SC2034 # Assignment through the caller-provided nameref.
	output_modules=("${modules[@]}")
}

target_modules=()
parent_modules=()
load_profile_modules "${profile_definition}" "${profile}" target_modules
load_profile_modules "${parent_definition}" "${parent_profile}" parent_modules

[[ "${#parent_modules[@]}" -eq 2 && "${parent_modules[0]}" == base && "${parent_modules[1]}" == hardware-* ]] || {
	echo "Parent profile ${parent_profile} must contain only base and one hardware module" >&2
	exit 2
}
[[ "${#target_modules[@]}" -ge 3 && "${target_modules[0]}" == base && "${target_modules[-1]}" == "${parent_modules[1]}" ]] || {
	echo "Derived profile ${profile} must inherit the hardware module from ${parent_profile}" >&2
	exit 2
}

delta_modules=("${target_modules[@]:1:${#target_modules[@]}-2}")
declare -A applied_modules=()
for module in "${delta_modules[@]}"; do
	[[ "${module}" =~ ${valid_name} && "${module}" != base && "${module}" != hardware-* ]] || {
		echo "Invalid derived module in ${profile}: ${module}" >&2
		exit 2
	}
	[[ -z "${applied_modules[${module}]:-}" ]] || { echo "Duplicate module in ${profile}: ${module}" >&2; exit 2; }
	module_script="${module_root}/${module}.sh"
	[[ -x "${module_script}" ]] || { echo "Unknown module in ${profile}: ${module}" >&2; exit 2; }
	applied_modules["${module}"]=1
done

if [[ "${PURPLEFIN_DERIVED_DRY_RUN:-false}" == true ]]; then
	printf '%s\n' "${delta_modules[@]}"
	exit 0
fi

for module in "${delta_modules[@]}"; do
	echo ":: Applying Purplefin derived module: ${module}"
	"${module_root}/${module}.sh"
done

# shellcheck source=/tmp/purplefin-build/lib/finalize-profile.sh
source "${build_root}/lib/finalize-profile.sh"
purplefin_update_independently_managed_rpms "${build_root}"
purplefin_finalize_profile "${profile}" "${target_modules[@]}"
