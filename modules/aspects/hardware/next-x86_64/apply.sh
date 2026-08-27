#!/usr/bin/env bash
set -euo pipefail

build_root="${FINITE_BUILD_ROOT:-/tmp/finite-build}"
generated_root="${FINITE_GENERATED_ROOT:?FINITE_GENERATED_ROOT is required}"
kernel_root="${generated_root}/bootc/generated/kernel-next"
lock="${kernel_root}/kernel-next.json"

[[ -r "${lock}" ]] || {
	echo "Missing next-kernel source lock: ${lock}" >&2
	exit 1
}
jq -e '
  .schema == 1 and
  (.release | test("^7[.]2[.][0-9]+-[0-9]+[.]fc45[.]x86_64$")) and
  (.packages | map(.name)) == [
    "kernel", "kernel-core", "kernel-modules-core",
    "kernel-modules", "kernel-modules-extra"
  ] and
  (.requiredModules | sort) == [
    "intel_cvs", "intel_ipu7", "intel_ipu7_isys", "ipu_bridge", "ov02c10"
  ]
' "${lock}" >/dev/null

release=$(jq -er '.release' "${lock}")
rpms=()
while IFS=$'\t' read -r name file sha256; do
	rpm_file="${kernel_root}/${file}"
	[[ -f "${rpm_file}" ]] || {
		echo "Missing locked next-kernel RPM: ${file}" >&2
		exit 1
	}
	printf '%s  %s\n' "${sha256}" "${rpm_file}" | sha256sum --check --strict
	[[ "$(rpm -qp --qf '%{NAME}' "${rpm_file}")" == "${name}" ]]
	[[ "$(rpm -qp --qf '%{EVR}.%{ARCH}' "${rpm_file}")" == "${release}" ]]
	rpms+=("${rpm_file}")
done < <(jq -r '.packages[] | [.name, .file, .sha256] | @tsv' "${lock}")

# Bluefin may carry build-only kernel packages and an external v4l2loopback
# kmod tied to its inherited kernel. They are not runtime dependencies of the
# next image and can prevent the pinned Fedora kernel transaction.
cleanup_packages=()
for package in kernel-devel kernel-devel-matched kmod-v4l2loopback v4l2loopback; do
	if rpm -q "${package}" >/dev/null 2>&1; then
		cleanup_packages+=("${package}")
	fi
done
if ((${#cleanup_packages[@]} > 0)); then
	dnf5 -y remove --no-autoremove "${cleanup_packages[@]}"
fi

dnf5 -y install --allowerasing "${rpms[@]}"

# A bootc image has one authoritative runtime kernel. Remove any inherited
# version only after the complete pinned replacement has installed.
stale_kernel_packages=()
for package in kernel kernel-core kernel-modules-core kernel-modules kernel-modules-extra; do
	while IFS=$'\t' read -r installed_nevra installed_release; do
		[[ "${installed_release}" == "${release}" ]] || stale_kernel_packages+=("${installed_nevra}")
	done < <(rpm -q --qf '%{NAME}-%{EVR}.%{ARCH}\t%{EVR}.%{ARCH}\n' "${package}")
done
if ((${#stale_kernel_packages[@]} > 0)); then
	dnf5 -y remove --no-autoremove "${stale_kernel_packages[@]}"
fi

for package in kernel kernel-core kernel-modules-core kernel-modules kernel-modules-extra; do
	[[ "$(rpm -q --qf '%{EVR}.%{ARCH}\n' "${package}")" == "${release}" ]]
done
depmod -a "${release}"

while IFS= read -r module; do
	module_path=$(modinfo -k "${release}" -F filename "${module}")
	[[ "${module_path}" == "/lib/modules/${release}/kernel/"* ]]
	[[ "$(modinfo -k "${release}" -F intree "${module}")" == Y ]]
	[[ "$(modinfo -k "${release}" -F signer "${module}")" == *Fedora* ]]
done < <(jq -r '.requiredModules[]' "${lock}")

source "${build_root}/bootc/builder/lib/authselect-features.sh"
source "${build_root}/bootc/builder/lib/hardware-security.sh"
finite_apply_hardware_security next-x86_64
