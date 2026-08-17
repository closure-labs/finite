#!/usr/bin/env bash
set -euo pipefail

build_root="${PURPLEFIN_BUILD_ROOT:-/tmp/purplefin-build}"
profile_root="${build_root}/modules/aspects/hardware/dell-xps-9350-intel/rootfs"

# shellcheck source=/tmp/purplefin-build/lib/dell-xps-9350-common.sh
# shellcheck disable=SC1091
source "${build_root}/bootc/builder/lib/dell-xps-9350-common.sh"

echo ":: Applying Dell XPS 9350 Intel hardware overlay"
cp -a "${profile_root}/." /
chmod 0755 /usr/libexec/purplefin/configure-firefox-pipewire-camera
chmod 0755 /usr/libexec/purplefin/install-refind-theme

# shellcheck source=/usr/libexec/purplefin/lib/dell-ipu7.sh
# shellcheck disable=SC1091
source /usr/libexec/purplefin/lib/dell-ipu7.sh

camera_runtime_packages=(
	libcamera
	libcamera-ipa
	libcamera-tools
	pipewire-plugin-libcamera
)
svp7500_make_args=()

installed_kernel_core_record() {
	local records=()

	mapfile -t records < <(rpm -q --qf $'%{version}\t%{evr}\t%{arch}\n' kernel-core)
	if ((${#records[@]} != 1)); then
		echo "Dell IPU7 profile requires exactly one inherited kernel-core, found ${#records[@]}" >&2
		return 1
	fi
	printf '%s\n' "${records[0]}"
}

install_svp7500_module() {
	local source_root="$1"
	local target_release="$2"
	local source_dir="$3"
	local module_file="$4"
	local module_name="${5:-${module_file%.ko}}"
	local source_path="${source_root}/dkms/${source_dir}"
	local built_path="${source_path}/${module_file}"
	local installed_path="/usr/lib/modules/${target_release}/updates/purplefin/${module_file}"
	local vermagic

	test -f "${source_path}/Makefile" || {
		echo "SVP7500 fix pack is missing ${source_dir}/Makefile" >&2
		return 1
	}

	echo ":: Building ${module_name} from SVP7500 fix pack"
	make -C "/usr/lib/modules/${target_release}/build" \
		M="${source_path}" \
		"${svp7500_make_args[@]}" \
		modules

	test -f "${built_path}" || {
		echo "SVP7500 build did not produce ${built_path}" >&2
		return 1
	}
	vermagic="$(modinfo -F vermagic "${built_path}")"
	if [[ "${vermagic%% *}" != "${target_release}" ]]; then
		echo "${module_name} vermagic ${vermagic} does not match ${target_release}" >&2
		return 1
	fi

	install -D -m 0644 "${built_path}" "${installed_path}"
}

assert_external_module_selected() {
	local target_release="$1"
	local module_name="$2"
	local expected_file="$3"
	local selected

	selected="$(modinfo -k "${target_release}" -n "${module_name}")"
	case "${selected}" in
		*/updates/purplefin/"${expected_file}") ;;
		*)
			echo "${module_name} resolves to ${selected}, not Purplefin's SVP7500 module" >&2
			return 1
			;;
	esac
}

install_svp7500_stack() {
	local inherited_record target_evr target_arch target_release
	local config_path kernel_devel_spec source_root checkout actual_ref module
	local int3472_provider="in-tree"
	local ipu7_firmware_path initramfs_path initramfs_listing initramfs_dracut_modules
	local initramfs_modules=(
		usbio
		gpio_usbio
		i2c_usbio
		intel_cvs
		ipu_bridge
		hm1092
		ov02c10
		intel_ipu7
	)
	local required_initramfs_dracut_modules=(
		ostree
		dmsquash-live
		dmsquash-live-autooverlay
	)
	local build_packages=(git make)
	local temporary_build_packages=()
	local cleanup_packages=()
	local package

	ipu7_firmware_path="$(purplefin_dell_ipu7_find_firmware)" || exit 1
	echo ":: Found Dell IPU7 firmware ${ipu7_firmware_path}"

	inherited_record="$(installed_kernel_core_record)"
	IFS=$'\t' read -r _ target_evr target_arch <<<"${inherited_record}"
	target_release="$(purplefin_dell_ipu7_kernel_release_for_evr_arch "${target_evr}" "${target_arch}")"

	config_path="$(purplefin_dell_ipu7_find_local_kernel_config "${target_release}")" || {
		echo "Dell IPU7 kernel config for ${target_release} is missing" >&2
		exit 1
	}
	purplefin_dell_ipu7_validate_kernel_config_file "${config_path}"
	purplefin_dell_ipu7_assert_replaceable_module "${target_release}" ipu-bridge
	if grep -qxF 'CONFIG_CC_IS_CLANG=y' "${config_path}"; then
		echo ":: Matching the inherited kernel's Clang/LLVM toolchain"
		build_packages+=(clang lld llvm)
		svp7500_make_args=(CC=clang LD=ld.lld LLVM=1)
	elif grep -qxF 'CONFIG_CC_IS_GCC=y' "${config_path}"; then
		echo ":: Matching the inherited kernel's GCC toolchain"
		build_packages+=(gcc)
		svp7500_make_args=(CC=gcc)
	else
		echo "Cannot determine the compiler used for inherited kernel ${target_release}" >&2
		exit 1
	fi

	test -d "/usr/lib/modules/${target_release}/build" || {
		kernel_devel_spec="kernel-devel-${target_evr#0:}.${target_arch}"
		build_packages+=("${kernel_devel_spec}")
	}

	for package in "${build_packages[@]}"; do
		if ! rpm -q "${package}" >/dev/null 2>&1; then
			temporary_build_packages+=("${package}")
		fi
	done

	echo ":: Installing temporary SVP7500 module build dependencies"
	dnf5 -y install "${build_packages[@]}"
	test -d "/usr/lib/modules/${target_release}/build" || {
		echo "Kernel build tree for ${target_release} is missing after installing build dependencies" >&2
		exit 1
	}

	source_root="$(mktemp -d /tmp/purplefin-svp7500.XXXXXX)"
	checkout="${source_root}/fix-pack"
	git init -q "${checkout}"
	git -C "${checkout}" remote add origin "$(purplefin_dell_ipu7_fix_pack_repo)"
	git -C "${checkout}" fetch --depth 1 origin "$(purplefin_dell_ipu7_fix_pack_ref)"
	git -C "${checkout}" checkout --quiet --detach FETCH_HEAD
	actual_ref="$(git -C "${checkout}" rev-parse HEAD)"
	if [[ "${actual_ref}" != "$(purplefin_dell_ipu7_fix_pack_ref)" ]]; then
		echo "SVP7500 fix pack resolved to ${actual_ref}, expected $(purplefin_dell_ipu7_fix_pack_ref)" >&2
		exit 1
	fi

	install_svp7500_module "${checkout}" "${target_release}" intel-cvs-1.0 intel_cvs.ko intel_cvs
	install_svp7500_module "${checkout}" "${target_release}" ipu-bridge-patched-1.0 ipu-bridge.ko ipu_bridge
	install_svp7500_module "${checkout}" "${target_release}" hm1092-1.0 hm1092.ko hm1092

	if purplefin_dell_ipu7_int3472_patch_needed "${target_release}"; then
		int3472_provider="svp7500-fix-pack"
		initramfs_modules+=(
			intel_skl_int3472_common
			intel_skl_int3472_discrete
		)
		install_svp7500_module \
			"${checkout}" "${target_release}" int3472-patched-1.0 \
			intel_skl_int3472_discrete.ko intel_skl_int3472_discrete
		install_svp7500_module \
			"${checkout}" "${target_release}" int3472-patched-1.0 \
			intel_skl_int3472_common.ko intel_skl_int3472_common
	else
		echo ":: Keeping in-tree INT3472 driver; it already exposes the IR flood LED"
	fi

	install -D -m 0644 "${checkout}/dkms/intel-cvs-1.0/LICENSE.txt" \
		/usr/share/licenses/purplefin-svp7500-camera-fix-pack/LICENSE.intel-cvs.txt
	install -d -m 0755 /usr/share/purplefin/dell-ipu7
	cat >/usr/share/purplefin/dell-ipu7/source-provenance <<EOF
source_repo=$(purplefin_dell_ipu7_fix_pack_repo)
source_version=$(purplefin_dell_ipu7_fix_pack_version)
source_commit=${actual_ref}
kernel_release=${target_release}
modules=intel_cvs ipu_bridge hm1092
int3472_provider=${int3472_provider}
EOF

	depmod -a "${target_release}"
	assert_external_module_selected "${target_release}" intel_cvs intel_cvs.ko
	assert_external_module_selected "${target_release}" ipu_bridge ipu-bridge.ko
	assert_external_module_selected "${target_release}" hm1092 hm1092.ko
	if [[ "${int3472_provider}" == "svp7500-fix-pack" ]]; then
		assert_external_module_selected \
			"${target_release}" intel_skl_int3472_discrete intel_skl_int3472_discrete.ko
	fi

	for module in INTC10CF INTC10DE INTC10E0 INTC10E1; do
		modinfo -k "${target_release}" -F alias intel_cvs | grep -qxF "acpi*:${module}:*"
	done
	modinfo -k "${target_release}" -F alias hm1092 | grep -qxF 'acpi*:HIMX1092:*'

	initramfs_path="/usr/lib/modules/${target_release}/initramfs.img"
	test -f "${initramfs_path}" || {
		echo "Inherited initramfs ${initramfs_path} is missing" >&2
		exit 1
	}

	echo ":: Rebuilding ${target_release} initramfs with the SVP7500 replacements"
	dracut \
		--add-drivers "${initramfs_modules[*]}" \
		--install "${ipu7_firmware_path}" \
		--rebuild "${initramfs_path}"
	initramfs_listing="$(lsinitrd "${initramfs_path}")"
	if ! awk -v firmware="${ipu7_firmware_path#/}" \
		'$NF == firmware { found = 1 } END { exit !found }' <<<"${initramfs_listing}"; then
		echo "Rebuilt initramfs does not contain Dell IPU7 firmware ${ipu7_firmware_path}" >&2
		exit 1
	fi
	for module in intel_cvs ipu-bridge hm1092; do
		if ! grep -qF "updates/purplefin/${module}.ko" <<<"${initramfs_listing}"; then
			echo "Rebuilt initramfs does not contain Purplefin's ${module} replacement" >&2
			exit 1
		fi
	done

	initramfs_dracut_modules="$(lsinitrd -m "${initramfs_path}")"
	for module in "${required_initramfs_dracut_modules[@]}"; do
		if ! grep -qxF "${module}" <<<"${initramfs_dracut_modules}"; then
			echo "Rebuilt initramfs lost required boot module ${module}" >&2
			exit 1
		fi
	done

	rm -rf "${source_root}"
	for package in "${temporary_build_packages[@]}"; do
		cleanup_packages+=("${package}")
	done
	if ((${#cleanup_packages[@]} > 0)); then
		echo ":: Removing SVP7500 build-only packages"
		dnf5 -y remove --no-autoremove "${cleanup_packages[@]}"
	fi
}

echo ":: Installing Fedora libcamera runtime"
dnf5 -y install "${camera_runtime_packages[@]}"

echo ":: Installing Dell OV02C10 libcamera IPA helper"
"${build_root}/modules/aspects/hardware/dell-xps-9350-intel/build/install-libcamera-ov02c10-ipa.sh"

install_svp7500_stack

purplefin_configure_dell_xps_9350_common

echo ":: Enabling Dell XPS 9350 Intel rEFInd theme installer"
systemctl enable purplefin-refind-theme.service
