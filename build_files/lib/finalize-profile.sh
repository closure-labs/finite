#!/usr/bin/env bash

purplefin_update_independently_managed_rpms() {
	local build_root="$1"
	local package
	local -a installed_independently_managed_rpms=()

	# shellcheck source=/tmp/purplefin-build/lib/independently-managed-rpms.sh
	source "${build_root}/lib/independently-managed-rpms.sh"
	independently_managed_rpms=()
	independently_managed_rpm_repo_args=()
	purplefin_load_independently_managed_rpms "${build_root}/independently-managed-rpms.list"
	for package in "${independently_managed_rpms[@]}"; do
		if rpm -q "${package}" >/dev/null 2>&1; then
			installed_independently_managed_rpms+=("${package}")
		fi
	done
	if ((${#installed_independently_managed_rpms[@]} > 0)); then
		echo ":: Updating independently managed RPMs"
		dnf5 -y --refresh "${independently_managed_rpm_repo_args[@]}" \
			upgrade "${installed_independently_managed_rpms[@]}"
		for package in "${installed_independently_managed_rpms[@]}"; do
			rpm -q "${package}"
		done
	fi
}

purplefin_finalize_profile() {
	local profile="$1"
	shift
	local -a profile_modules=("$@")
	local -a installed_kernel_releases=()

	install -d /usr/share/purplefin
	printf '%s\n' "${profile}" >/usr/share/purplefin/build-profile
	printf '%s\n' "${profile_modules[@]}" >/usr/share/purplefin/build-modules
	printf '%s\n' "${PURPLEFIN_VERSION:?PURPLEFIN_VERSION is required}" >/usr/share/purplefin/version

	if [[ -d /usr/libexec/purplefin/firstboot-rpm-ostree.d ]]; then
		find /usr/libexec/purplefin/firstboot-rpm-ostree.d -maxdepth 1 -type f -exec chmod 0755 {} +
	fi
	if [[ -d /usr/libexec/purplefin/firstboot-rpm-ostree.d ]] && find /usr/libexec/purplefin/firstboot-rpm-ostree.d -maxdepth 1 -type f -perm /111 -print -quit | grep -q .; then
		systemctl enable purplefin-firstboot-rpm-ostree.service
	fi

	[[ -n "${PURPLEFIN_OSTREE_LINUX:-}" ]] || { echo 'PURPLEFIN_OSTREE_LINUX is required' >&2; exit 1; }
	mapfile -t installed_kernel_releases < <(rpm -q --qf '%{EVR}.%{ARCH}\n' kernel-core)
	if ((${#installed_kernel_releases[@]} != 1)) || [[ "${installed_kernel_releases[0]}" != "${PURPLEFIN_OSTREE_LINUX}" ]]; then
		echo "Kernel payload does not match ostree.linux=${PURPLEFIN_OSTREE_LINUX}" >&2
		exit 1
	fi
	dnf5 clean all
	rm -f /boot/symvers-*.xz
	rm -rf /run/dnf /var/cache/libdnf5 /var/cache/ldconfig/aux-cache /var/lib/authselect/backups /var/lib/dnf/repos /var/lib/dnf/system-repo.lock /var/lib/rpm-state /var/log/dnf5.log*
}
