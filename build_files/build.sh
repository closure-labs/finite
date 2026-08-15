#!/usr/bin/env bash
set -euo pipefail

build_root="${PURPLEFIN_BUILD_ROOT:-/tmp/purplefin-build}"
profile="${1:-${BUILD_PROFILE:-base-generic}}"
profile_definition="${build_root}/profiles/profiles/${profile}.conf"
module_root="${build_root}/modules"
modules=()

valid_name='^[a-z0-9._-]+$'
[[ "${profile}" =~ ${valid_name} ]] || { echo "Invalid build profile: ${profile}" >&2; exit 2; }

[[ -f "${profile_definition}" ]] || { echo "Unknown build profile: ${profile}" >&2; exit 2; }
# shellcheck source=/dev/null
source "${profile_definition}"
[[ "${profile_name:-}" == "${profile}" ]] || { echo "Invalid profile definition: ${profile_definition}" >&2; exit 2; }
declare -p modules >/dev/null 2>&1 || { echo "Profile ${profile} does not define modules" >&2; exit 2; }

# shellcheck source=/tmp/purplefin-build/profiles/lib/authselect-features.sh
source "${build_root}/profiles/lib/authselect-features.sh"
# shellcheck source=/tmp/purplefin-build/profiles/lib/hardware-security.sh
source "${build_root}/profiles/lib/hardware-security.sh"
purplefin_authselect_reset

hardware_count=0
declare -A applied_modules=()
for module in "${modules[@]}"; do
	[[ "${module}" =~ ${valid_name} ]] || { echo "Invalid module in ${profile}: ${module}" >&2; exit 2; }
	[[ -z "${applied_modules[${module}]:-}" ]] || { echo "Duplicate module in ${profile}: ${module}" >&2; exit 2; }
	module_script="${module_root}/${module}.sh"
	[[ -x "${module_script}" ]] || { echo "Unknown module in ${profile}: ${module}" >&2; exit 2; }
	if [[ "${module}" == hardware-* ]]; then
		((hardware_count += 1))
	fi
	if [[ "${module}" == base ]]; then
		[[ "${#applied_modules[@]}" -eq 0 ]] || { echo "base must be the first module in ${profile}" >&2; exit 2; }
	fi
	echo ":: Applying Purplefin module: ${module}"
	"${module_script}"
	applied_modules["${module}"]=1
done

[[ -n "${applied_modules[base]:-}" ]] || { echo "Profile ${profile} must include base" >&2; exit 2; }
[[ "${hardware_count}" -eq 1 ]] || { echo "Profile ${profile} must include exactly one hardware module" >&2; exit 2; }

# The full build owns authentication-stack generation. Derived builds inherit
# that completed hardware policy and intentionally do not reset it.
purplefin_authselect_finalize
# shellcheck source=/tmp/purplefin-build/lib/finalize-profile.sh
source "${build_root}/lib/finalize-profile.sh"
purplefin_update_independently_managed_rpms "${build_root}"
purplefin_finalize_profile "${profile}" "${modules[@]}"
