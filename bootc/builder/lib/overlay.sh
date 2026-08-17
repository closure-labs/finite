#!/usr/bin/env bash
# Shared helpers for applying aspect-owned root filesystems and manifests.

purplefin_apply_overlay() {
	local aspect_root="$1"
	local manifest_name="$2"
	local build_root="${PURPLEFIN_BUILD_ROOT:-/tmp/purplefin-build}"
	local source_root="${build_root}/${aspect_root}"
	local system_root="${source_root}/rootfs"
	local flatpak_manifest="${source_root}/manifests/flatpaks.preinstall"

	if [[ -d "${system_root}" ]]; then
		cp -a "${system_root}/." /
	fi

	if [[ -f "${flatpak_manifest}" ]]; then
		install -D -m 0644 "${flatpak_manifest}" \
			"/usr/share/flatpak/preinstall.d/${manifest_name}.preinstall"
	fi
}

purplefin_apply_role_overlay() {
	local role="$1"
	purplefin_apply_overlay "modules/aspects/roles/${role}" "purplefin-${role}"
}

purplefin_apply_component_overlay() {
	local component="$1"
	local build_root="${PURPLEFIN_BUILD_ROOT:-/tmp/purplefin-build}"
	local component_root="${build_root}/modules/aspects/capabilities/${component}"

	if [[ -d "${component_root}/rootfs" ]]; then
		cp -a "${component_root}/rootfs/." /
	fi
	if [[ -f "${component_root}/manifests/flatpaks.preinstall" ]]; then
		install -D -m 0644 "${component_root}/manifests/flatpaks.preinstall" \
			"/usr/share/flatpak/preinstall.d/purplefin-component-${component}.preinstall"
	fi
}
