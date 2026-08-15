#!/usr/bin/env bash
# Apply authentication hardware support shared by every Purplefin hardware profile.

purplefin_apply_hardware_security() {
	local hardware_profile="${1:-unknown}"
	local security_packages=(
		fprintd
		fprintd-pam
		libfprint
		pam-u2f
		pamu2fcfg
		libfido2
		opensc
		pcsc-lite
		yubikey-manager
	)

	if [[ "${PURPLEFIN_HARDWARE_SECURITY_APPLIED:-0}" == 1 ]]; then
		echo ":: Shared hardware security already applied for ${hardware_profile}"
		return 0
	fi

	echo ":: Installing shared hardware security for ${hardware_profile}"
	dnf5 -y install "${security_packages[@]}"

	local package
	for package in "${security_packages[@]}"; do
		rpm -q "${package}"
	done

	purplefin_authselect_request with-fingerprint with-pam-u2f
	systemctl enable pcscd.socket
	PURPLEFIN_HARDWARE_SECURITY_APPLIED=1
}
