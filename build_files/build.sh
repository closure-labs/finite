#!/usr/bin/env bash
set -euo pipefail

build_root="${PURPLEFIN_BUILD_ROOT:-/tmp/purplefin-build}"
profile_files_root="${PURPLEFIN_PROFILE_FILES_ROOT:-/tmp/purplefin-profile-files}"
profile="${1:-${BUILD_PROFILE:-base-generic}}"
legacy_role="${2:-${BUILD_ROLE:-}}"
profile_definition="${build_root}/profiles/profiles/${profile}.conf"
module_root="${build_root}/modules"

valid_name='^[a-z0-9._-]+$'
[[ "${profile}" =~ ${valid_name} ]] || { echo "Invalid build profile: ${profile}" >&2; exit 2; }

# A named profile is the public composition interface.  The legacy role plus
# hardware pair remains accepted so existing callers can migrate gradually.
if [[ -f "${profile_definition}" ]]; then
	# shellcheck source=/dev/null
	source "${profile_definition}"
	[[ "${profile_name:-}" == "${profile}" ]] || { echo "Invalid profile definition: ${profile_definition}" >&2; exit 2; }
	declare -p modules >/dev/null 2>&1 || { echo "Profile ${profile} does not define modules" >&2; exit 2; }
else
	[[ -x "${build_root}/profiles/${profile}.sh" ]] || { echo "Unknown build profile: ${profile}" >&2; exit 2; }
	legacy_role="${legacy_role:-base}"
	[[ "${legacy_role}" =~ ${valid_name} && -x "${build_root}/profiles/roles/${legacy_role}.sh" ]] || {
		echo "Unknown legacy build role: ${legacy_role}" >&2; exit 2;
	}
	profile="legacy-${legacy_role}-${profile}"
	modules=(base "legacy-role-${legacy_role}" "legacy-hardware-${1:-${BUILD_PROFILE:-generic-x86_64}}")
fi

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
	if [[ "${module}" == hardware-* || "${module}" == legacy-hardware-* ]]; then
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

# Independently managed RPMs may belong to only some profiles, so update the
# installed subset after every role and hardware module has been applied.
# shellcheck source=/tmp/purplefin-build/lib/independently-managed-rpms.sh
source "${build_root}/lib/independently-managed-rpms.sh"
purplefin_load_independently_managed_rpms "${build_root}/independently-managed-rpms.list"
installed_independently_managed_rpms=()
for package in "${independently_managed_rpms[@]}"; do
	if rpm -q "${package}" >/dev/null 2>&1; then
		installed_independently_managed_rpms+=("${package}")
	fi
done
if ((${#installed_independently_managed_rpms[@]} > 0)); then
	echo ":: Updating independently managed RPMs"
	dnf5 -y --refresh "${independently_managed_rpm_repo_args[@]}" \
		upgrade "${installed_independently_managed_rpms[@]}"
	for package in "${installed_independently_managed_rpms[@]}"; do rpm -q "${package}"; done
fi

install -d /usr/share/purplefin
printf '%s\n' "${profile}" > /usr/share/purplefin/build-profile
printf '%s\n' "${modules[@]}" > /usr/share/purplefin/build-modules

if [[ -d /usr/libexec/purplefin/firstboot-rpm-ostree.d ]]; then
	find /usr/libexec/purplefin/firstboot-rpm-ostree.d -maxdepth 1 -type f -exec chmod 0755 {} +
fi
if [[ -d /usr/libexec/purplefin/firstboot-rpm-ostree.d ]] && find /usr/libexec/purplefin/firstboot-rpm-ostree.d -maxdepth 1 -type f -perm /111 -print -quit | grep -q .; then
	systemctl enable purplefin-firstboot-rpm-ostree.service
fi

purplefin_authselect_finalize

[[ -n "${PURPLEFIN_OSTREE_LINUX:-}" ]] || { echo 'PURPLEFIN_OSTREE_LINUX is required' >&2; exit 1; }
mapfile -t installed_kernel_releases < <(rpm -q --qf '%{EVR}.%{ARCH}\n' kernel-core)
if ((${#installed_kernel_releases[@]} != 1)) || [[ "${installed_kernel_releases[0]}" != "${PURPLEFIN_OSTREE_LINUX}" ]]; then
	echo "Kernel payload does not match ostree.linux=${PURPLEFIN_OSTREE_LINUX}" >&2
	exit 1
fi
dnf5 clean all
rm -f /boot/symvers-*.xz
rm -rf /run/dnf /var/cache/libdnf5 /var/cache/ldconfig/aux-cache /var/lib/authselect/backups /var/lib/dnf/repos /var/lib/dnf/system-repo.lock /var/lib/rpm-state /var/log/dnf5.log*
