#!/usr/bin/env bash
set -euo pipefail

profile_root="/tmp/purplefin-profile-files/dell-xps-9350-intel/system_files"

# shellcheck source=/tmp/purplefin-build/profiles/lib/dell-xps-9350-common.sh
# shellcheck disable=SC1091
source /tmp/purplefin-build/profiles/lib/dell-xps-9350-common.sh

copy_profile_file() {
	local relative_path="$1"
	local source="${profile_root}/${relative_path}"
	local target="/${relative_path}"

	if [[ ! -e "${source}" ]]; then
		echo "Missing Dell profile source file: ${source}" >&2
		exit 1
	fi

	install -d -m 0755 "$(dirname "${target}")"
	cp -a "${source}" "${target}"
}

copy_profile_tree() {
	local relative_path="$1"
	local source="${profile_root}/${relative_path}"
	local target="/${relative_path}"

	if [[ ! -d "${source}" ]]; then
		echo "Missing Dell profile source directory: ${source}" >&2
		exit 1
	fi

	install -d -m 0755 "${target}"
	cp -a "${source}/." "${target}/"
}

echo ":: Applying Dell XPS 9350 Intel no-camera test overlay"
copy_profile_file "etc/pam.d/polkit-1"
copy_profile_file "etc/pam.d/purplefin-dell-lid-auth"
copy_profile_file "etc/pam.d/purplefin-dell-password-auth"
copy_profile_file "etc/pam.d/sudo"
copy_profile_file "usr/libexec/purplefin/install-refind-theme"
copy_profile_file "usr/libexec/purplefin/dell-lid-is-open"
copy_profile_file "usr/lib/systemd/system/purplefin-refind-theme.service"
copy_profile_tree "usr/share/purplefin/refind"
copy_profile_file "usr/lib/purplefin/dell-xps-9350-battery.conf"
copy_profile_file "usr/lib/udev/hwdb.d/61-purplefin-dell-xps-9350-battery.hwdb"
copy_profile_file "usr/lib/tuned/profiles/purplefin-dell-xps-9350-performance/tuned.conf"
copy_profile_file "usr/lib/systemd/system/purplefin-dell-xps-9350-battery.service"
copy_profile_file "usr/libexec/purplefin/configure-dell-xps-9350-battery"
copy_profile_file "usr/lib/systemd/user/purplefin-dell-xps-9350-panel.service"
copy_profile_file "usr/libexec/purplefin/dell-xps-9350-panel-policy"
copy_profile_file "usr/share/purplefin/dell-xps-9350-panel.conf"
copy_profile_file "usr/share/glib-2.0/schemas/zz9-purplefin-dell-xps-9350.gschema.override"
copy_profile_file "etc/systemd/user/graphical-session.target.wants/purplefin-dell-xps-9350-panel.service"

chmod 0755 /usr/libexec/purplefin/install-refind-theme

purplefin_configure_dell_xps_9350_common

echo ":: Enabling Dell XPS 9350 Intel rEFInd theme installer"
systemctl enable purplefin-refind-theme.service
