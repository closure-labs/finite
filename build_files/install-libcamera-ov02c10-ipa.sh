#!/usr/bin/env bash
set -euo pipefail

source_version="0.7.1"
source_sha256="27a6d776bb728bb8bd38c4594ff3ab7fadfce19583427de8442963ef2fe5ad04"
source_url="https://gitlab.freedesktop.org/camera/libcamera/-/archive/v${source_version}/libcamera-v${source_version}.tar.bz2"
patch_file="/tmp/purplefin-build/libcamera/0001-libipa-add-ov02c10-helper.patch"
install_dir="/usr/lib64/libcamera/ipa-purplefin"
workdir="$(mktemp -d)"
temporary_build_packages=()

cleanup() {
	local package

	rm -rf "${workdir}"
	if ((${#temporary_build_packages[@]} > 0)); then
		echo ":: Removing libcamera IPA build-only packages"
		dnf5 -y remove --no-autoremove "${temporary_build_packages[@]}"
		for package in "${temporary_build_packages[@]}"; do
			if rpm -q "${package}" >/dev/null 2>&1; then
				echo "Temporary libcamera build dependency is still installed: ${package}" >&2
				return 1
			fi
		done
	fi
}
trap cleanup EXIT

[[ -f "${patch_file}" ]] || {
	echo "Missing OV02C10 libcamera patch: ${patch_file}" >&2
	exit 1
}

installed_version="$(rpm -q --qf '%{VERSION}' libcamera)"
if [[ "${installed_version}" != "${source_version}" ]]; then
	echo "OV02C10 IPA patch targets libcamera ${source_version}; installed version is ${installed_version}" >&2
	exit 1
fi

build_packages=(
	gcc-c++
	gnutls-devel
	libevent-devel
	libyaml-devel
	meson
	ninja-build
	patch
	patchelf
	pkgconf-pkg-config
	python3-jinja2
	python3-ply
	python3-pyyaml
)
rpm -qa --qf '%{NAME}\n' | sort -u >"${workdir}/packages-before-build"
dnf5 -y --setopt=install_weak_deps=False install "${build_packages[@]}"
mapfile -t temporary_build_packages < <(
	comm -13 "${workdir}/packages-before-build" <(rpm -qa --qf '%{NAME}\n' | sort -u)
)

archive="${workdir}/libcamera.tar.bz2"
source_root="${workdir}/libcamera-v${source_version}"
build_root="${workdir}/build"

echo ":: Building Purplefin OV02C10 libcamera IPA helper"
curl --fail --location --show-error --silent --retry 3 --retry-delay 2 \
	--output "${archive}" "${source_url}"
printf '%s  %s\n' "${source_sha256}" "${archive}" | sha256sum --check --strict
tar -xf "${archive}" -C "${workdir}"
patch --directory="${source_root}" --strip=1 <"${patch_file}"

# GCC 16 reports false-positive array-bounds warnings in libcamera 0.7.1's
# std::shared_ptr<std::mutex> code. Keep the diagnostics visible without
# treating unrelated upstream warnings as errors.
meson setup "${build_root}" "${source_root}" \
	--buildtype=release \
	-Dwerror=false \
	-Dandroid=disabled \
	-Dcam=disabled \
	-Ddocumentation=disabled \
	-Dgstreamer=disabled \
	-Dipas=simple \
	-Dlc-compliance=disabled \
	-Dlibdw=disabled \
	-Dlibunwind=disabled \
	-Dpipelines=simple \
	-Dpycamera=disabled \
	-Dqcam=disabled \
	-Dsoftisp-gpu=disabled \
	-Dtest=false \
	-Dtracing=disabled \
	-Dudev=disabled \
	-Dv4l2=disabled
meson compile -C "${build_root}" ipa_soft_simple

module="${build_root}/src/ipa/simple/ipa_soft_simple.so"
[[ -f "${module}" ]] || {
	echo "libcamera build did not produce ${module}" >&2
	exit 1
}
patchelf --remove-rpath "${module}"
if readelf -d "${module}" | grep -Eq 'RPATH|RUNPATH'; then
	echo "Built libcamera IPA still contains a build-only library path" >&2
	exit 1
fi
nm -D "${module}" >"${workdir}/module-symbols"
grep -qF 'CameraSensorHelperOv02c10' "${workdir}/module-symbols" || {
	echo "Built libcamera IPA does not contain the OV02C10 helper" >&2
	exit 1
}
readelf -d "${module}" | grep -qF 'Shared library: [libcamera.so.0.7]' || {
	echo "Built libcamera IPA does not target Fedora's libcamera 0.7 ABI" >&2
	exit 1
}

install -D -m 0755 "${module}" "${install_dir}/ipa_soft_simple.so"
ldd -r "${install_dir}/ipa_soft_simple.so" 2>&1 | tee "${workdir}/ldd-output"
if grep -Eq 'not found|undefined symbol' "${workdir}/ldd-output"; then
	echo "Installed OV02C10 IPA module has unresolved runtime dependencies" >&2
	exit 1
fi

install -d /usr/share/purplefin/dell-ipu7
cat >"/usr/share/purplefin/dell-ipu7/libcamera-ipa-provenance" <<EOF
source_url=${source_url}
source_version=${source_version}
source_sha256=${source_sha256}
patch=0001-libipa-add-ov02c10-helper.patch
module=${install_dir}/ipa_soft_simple.so
isolation=required
EOF
