#!/usr/bin/env bash
set -euo pipefail

build_root="${PURPLEFIN_BUILD_ROOT:-/tmp/purplefin-build}"
generated_root="${PURPLEFIN_GENERATED_ROOT:-${build_root}}"
profile="${1:-${BUILD_PROFILE:-base-generic}}"
profile_catalog="${generated_root}/bootc/generated/profile-catalog.json"
modules=()
build_steps=()

valid_name='^[a-z0-9._-]+$'
[[ "${profile}" =~ ${valid_name} ]] || { echo "Invalid build profile: ${profile}" >&2; exit 2; }

[[ -f "${profile_catalog}" ]] || { echo "Missing generated profile catalog: ${profile_catalog}" >&2; exit 2; }
jq -e --arg profile "${profile}" '.profiles[$profile]' "${profile_catalog}" >/dev/null || {
	echo "Unknown build profile: ${profile}" >&2
	exit 2
}
mapfile -t modules < <(jq -er --arg profile "${profile}" '.profiles[$profile].modules[]' "${profile_catalog}")
mapfile -t build_steps < <(
	jq -er --arg profile "${profile}" '.profiles[$profile].buildSteps[] | [.name, .script] | @tsv' "${profile_catalog}"
)

# shellcheck source=/tmp/purplefin-build/bootc/builder/lib/authselect-features.sh
source "${build_root}/bootc/builder/lib/authselect-features.sh"
# shellcheck source=/tmp/purplefin-build/bootc/builder/lib/hardware-security.sh
source "${build_root}/bootc/builder/lib/hardware-security.sh"
purplefin_authselect_reset

hardware_count=0
declare -A applied_steps=()
for build_step in "${build_steps[@]}"; do
	IFS=$'\t' read -r step_name step_script <<<"${build_step}"
	[[ "${step_name}" =~ ${valid_name} ]] || { echo "Invalid build step in ${profile}: ${step_name}" >&2; exit 2; }
	[[ -z "${applied_steps[${step_name}]:-}" ]] || { echo "Duplicate build step in ${profile}: ${step_name}" >&2; exit 2; }
	[[ "${step_script}" != /* && "${step_script}" != *..* ]] || { echo "Unsafe build-step path in ${profile}: ${step_script}" >&2; exit 2; }
	step_path="${build_root}/${step_script}"
	[[ -x "${step_path}" ]] || { echo "Missing build step in ${profile}: ${step_script}" >&2; exit 2; }
	if [[ "${step_name}" == hardware-* ]]; then
		((hardware_count += 1))
	fi
	if [[ "${step_name}" == base ]]; then
		[[ "${#applied_steps[@]}" -eq 0 ]] || { echo "base must be the first build step in ${profile}" >&2; exit 2; }
	fi
	echo ":: Applying Purplefin aspect: ${step_name}"
	"${step_path}"
	applied_steps["${step_name}"]=1
done

[[ -n "${applied_steps[base]:-}" ]] || { echo "Profile ${profile} must include base" >&2; exit 2; }
if [[ "${profile}" == base ]]; then
	[[ "${hardware_count}" -eq 0 ]] || { echo 'The common base cannot include a hardware aspect' >&2; exit 2; }
else
	[[ "${hardware_count}" -eq 1 ]] || { echo "Profile ${profile} must include exactly one hardware aspect" >&2; exit 2; }
fi

purplefin_authselect_finalize
# shellcheck source=/tmp/purplefin-build/bootc/builder/lib/finalize-profile.sh
source "${build_root}/bootc/builder/lib/finalize-profile.sh"
purplefin_update_independently_managed_rpms "${build_root}"
purplefin_finalize_profile "${profile}" "${modules[@]}"
