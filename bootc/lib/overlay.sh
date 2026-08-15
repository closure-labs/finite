#!/usr/bin/env bash
# Shared helpers for applying department and reusable-component overlays.

purplefin_apply_overlay() {
	local collection="$1"
	local name="$2"
	local manifest_name="$3"
	local build_root="${PURPLEFIN_BUILD_ROOT:-/tmp/purplefin-build}"
	local overlay_root="${build_root}/overlays/${collection}/${name}"
	local system_root="${overlay_root}/files"
	local flatpak_manifest="${overlay_root}/manifests/flatpaks.preinstall"

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
	purplefin_apply_overlay roles "${role}" "purplefin-${role}"
}

purplefin_apply_component_overlay() {
	local component="$1"
	local build_root="${PURPLEFIN_BUILD_ROOT:-/tmp/purplefin-build}"
	local component_root="${build_root}/components/${component}"

	if [[ -d "${component_root}/files" ]]; then
		cp -a "${component_root}/files/." /
	fi
	if [[ -f "${component_root}/manifests/flatpaks.preinstall" ]]; then
		install -D -m 0644 "${component_root}/manifests/flatpaks.preinstall" \
			"/usr/share/flatpak/preinstall.d/purplefin-component-${component}.preinstall"
	fi
}
