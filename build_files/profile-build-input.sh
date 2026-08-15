#!/usr/bin/env bash
set -euo pipefail

profile="${1:?usage: profile-build-input.sh PROFILE TAGS}"
tags="${2:?usage: profile-build-input.sh PROFILE TAGS}"
definition="build_files/profiles/profiles/${profile}.conf"
modules=()

[[ -f "${definition}" ]] || { echo "Unknown build profile: ${profile}" >&2; exit 2; }
# shellcheck source=/dev/null
source "${definition}"
[[ "${profile_name:-}" == "${profile}" ]] || { echo "Invalid profile definition: ${definition}" >&2; exit 2; }
declare -p modules >/dev/null 2>&1 || { echo "Profile ${profile} does not define modules" >&2; exit 2; }

paths=(
	.github/workflows/build.yml
	.github/workflows/build-profile.yml
	VERSION
	build_files/image-matrix.json
	build_files/independently-managed-rpms.list
	build_files/select-ostree-linux.sh
	"${definition}"
)

parent="$(jq -er --arg profile "${profile}" '.[] | select(.profile == $profile) | .parent // ""' build_files/image-matrix.json)"
if [[ -z "${parent}" ]]; then
	paths+=(
		Containerfile
		build_files/bitwarden-cli.env
		build_files/bitwarden-cli.spec
		build_files/build.sh
		build_files/install-bitwarden-cli-rpm.sh
		build_files/lib
		manifests
		system_files
	)
else
	paths+=(Containerfile.derived build_files/build-derived.sh build_files/lib)
fi

for module in "${modules[@]}"; do
	if [[ -n "${parent}" && ( "${module}" == base || "${module}" == hardware-* ) ]]; then
		continue
	fi
	paths+=("build_files/modules/${module}.sh" "profile_files/modules/${module}")
	case "${module}" in
		developer)
			paths+=(build_files/profiles/components/devops.sh build_files/profiles/lib/role-common.sh build_files/profiles/roles/development.sh profile_files/components/devops)
		;;
		support)
			paths+=(build_files/profiles/components/devops.sh build_files/profiles/lib/role-common.sh build_files/profiles/roles/support.sh profile_files/components/devops profile_files/roles/support)
		;;
		hardware-dell-xps-9350-intel)
			paths+=(build_files/install-libcamera-ov02c10-ipa.sh build_files/libcamera build_files/profiles/dell-xps-9350-intel.sh build_files/profiles/lib/dell-xps-9350-common.sh build_files/profiles/lib/hardware-security.sh build_files/profiles/lib/authselect-features.sh profile_files/dell-xps-9350-intel)
		;;
		hardware-*)
			paths+=(build_files/profiles/lib/hardware-security.sh build_files/profiles/lib/authselect-features.sh)
		;;
	esac
done

{
	printf 'profile=%s\ntags=%s\n' "${profile}" "${tags}"
	git ls-files -s -- "${paths[@]}"
} | sha256sum | cut -d ' ' -f 1
