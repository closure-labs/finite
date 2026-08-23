#!/usr/bin/env bash
# Shared image-build helpers for the Dell SVP7500/IPU7 camera stack.

finite_dell_ipu7_log() {
	printf 'finite-dell-ipu7: %s\n' "$*" >&2
}

finite_dell_ipu7_fix_pack_repo() {
	printf '%s\n' 'https://github.com/jibsta210/svp7500-camera-fix-pack'
}

finite_dell_ipu7_fix_pack_version() {
	printf '%s\n' 'v1.0.2'
}

finite_dell_ipu7_fix_pack_ref() {
	printf '%s\n' 'e4c95452339b2d9803974a899c4f2da6e143891d'
}

finite_dell_ipu7_kernel_release_for_evr_arch() {
	local evr="$1"
	local arch="$2"

	printf '%s.%s\n' "${evr#0:}" "${arch}"
}

finite_dell_ipu7_required_kernel_configs() {
	local configs="${FINITE_DELL_IPU7_REQUIRED_KERNEL_CONFIGS:-CONFIG_IPU_BRIDGE CONFIG_VIDEO_INTEL_IPU7 CONFIG_VIDEO_OV02C10 CONFIG_USB_USBIO CONFIG_GPIO_USBIO CONFIG_I2C_USBIO}"
	local config_list=()

	read -r -a config_list <<<"${configs}"
	printf '%s\n' "${config_list[@]}"
}

finite_dell_ipu7_validate_kernel_config_file() {
	local config_file="$1"
	local config value

	[[ -f "${config_file}" ]] || return 1
	while IFS= read -r config; do
		[[ -n "${config}" ]] || continue
		value="$(sed -n "s/^${config}=//p" "${config_file}")"
		if [[ "${value}" != "m" && "${value}" != "y" ]]; then
			finite_dell_ipu7_log "target kernel config ${config_file} does not enable ${config}"
			return 1
		fi
	done < <(finite_dell_ipu7_required_kernel_configs)
}

finite_dell_ipu7_find_local_kernel_config() {
	local release="$1"
	local config_file

	for config_file in \
		"/usr/lib/modules/${release}/config" \
		"/lib/modules/${release}/config" \
		"/boot/config-${release}"; do
		if [[ -f "${config_file}" ]]; then
			printf '%s\n' "${config_file}"
			return 0
		fi
	done

	return 1
}

finite_dell_ipu7_assert_replaceable_module() {
	local release="$1"
	local module_file="$2"
	local builtins="/usr/lib/modules/${release}/modules.builtin"

	if [[ -f "${builtins}" ]] && grep -qE "/${module_file}[.]ko$" "${builtins}"; then
		finite_dell_ipu7_log "${module_file} is built into ${release}; the SVP7500 replacement cannot take precedence"
		return 1
	fi
}

finite_dell_ipu7_int3472_patch_needed() {
	local release="$1"
	local module_base="/usr/lib/modules/${release}/kernel/drivers/platform/x86/intel/int3472/intel_skl_int3472_discrete.ko"
	local module_file module_text suffix

	for suffix in '' .xz .zst; do
		module_file="${module_base}${suffix}"
		[[ -f "${module_file}" ]] || continue

		case "${suffix}" in
			.xz)
				module_text="$(xz -dc "${module_file}" | strings)"
				;;
			.zst)
				module_text="$(zstd -dcq "${module_file}" | strings)"
				;;
			*)
				module_text="$(strings "${module_file}")"
				;;
		esac
		if grep -qE '^ir_flood$|skl_int3472_register_led' <<<"${module_text}"; then
			return 1
		fi
		return 0
	done

	return 0
}

finite_dell_ipu7_find_firmware() {
	local firmware_path firmware_root suffix
	local firmware_roots="${FINITE_DELL_IPU7_FIRMWARE_ROOTS:-/usr/lib/firmware/intel/ipu:/lib/firmware/intel/ipu}"
	local firmware_root_list=()

	IFS=: read -r -a firmware_root_list <<<"${firmware_roots}"
	for firmware_root in "${firmware_root_list[@]}"; do
		for suffix in '' .xz .zst; do
			firmware_path="${firmware_root}/ipu7_fw.bin${suffix}"
			if [[ -f "${firmware_path}" ]]; then
				printf '%s\n' "${firmware_path}"
				return 0
			fi
		done
	done

	echo "Dell IPU7 firmware ipu7_fw.bin, ipu7_fw.bin.xz, or ipu7_fw.bin.zst is missing" >&2
	return 1
}
