#!/usr/bin/env bash

purplefin_finalize_profile() {
	local profile="$1"
	local profile_catalog="$2"
	shift 2
	local -a profile_modules=("$@")
	local -a installed_kernel_releases=()

	install -d /usr/share/purplefin
	printf '%s\n' "${profile}" >/usr/share/purplefin/build-profile
	printf '%s\n' "${profile_modules[@]}" >/usr/share/purplefin/build-modules
	printf '%s\n' "${PURPLEFIN_VERSION:?PURPLEFIN_VERSION is required}" >/usr/share/purplefin/version
	jq -e --arg profile "${profile}" '.profiles[$profile]' \
		"${profile_catalog}" \
		>/usr/share/purplefin/profile.json

	if [[ -d /usr/libexec/purplefin/firstboot-rpm-ostree.d ]]; then
		find /usr/libexec/purplefin/firstboot-rpm-ostree.d -maxdepth 1 -type f -exec chmod 0755 {} +
	fi
	if [[ -d /usr/libexec/purplefin/firstboot-rpm-ostree.d ]] && find /usr/libexec/purplefin/firstboot-rpm-ostree.d -maxdepth 1 -type f -perm /111 -print -quit | grep -q .; then
		systemctl enable purplefin-firstboot-rpm-ostree.service
	fi

	mapfile -t installed_kernel_releases < <(rpm -q --qf '%{EVR}.%{ARCH}\n' kernel-core)
	if ((${#installed_kernel_releases[@]} != 1)); then
		echo 'Purplefin expects exactly one kernel inherited from its parent image' >&2
		exit 1
	fi
	dnf5 clean all
	rm -f /boot/symvers-*.xz
	rm -rf /run/dnf /var/cache/libdnf5 /var/cache/ldconfig/aux-cache /var/lib/authselect/backups /var/lib/dnf/repos /var/lib/dnf/system-repo.lock /var/lib/rpm-state /var/log/dnf5.log*
}
