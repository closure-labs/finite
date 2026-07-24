#!/usr/bin/env bash
set -euo pipefail

profile="${1:?usage: select-ostree-linux.sh PROFILE BASE_KERNEL_RELEASE}"
base_release="${2:?usage: select-ostree-linux.sh PROFILE BASE_KERNEL_RELEASE}"
minimum_version="${PURPLEFIN_DELL_IPU7_MINIMUM_KERNEL_VERSION:-7.1.2}"
pinned_evr="${PURPLEFIN_DELL_IPU7_DEFAULT_KERNEL_EVR:-7.1.2-355.vanilla.fc44}"
base_version="${base_release%%-*}"
base_arch="${base_release##*.}"

version_at_least() {
	local candidate="$1"
	local minimum="$2"
	local newest

	[[ "${candidate}" =~ ^[0-9]+([.][0-9]+)*$ ]]
	[[ "${minimum}" =~ ^[0-9]+([.][0-9]+)*$ ]]
	newest="$(printf '%s\n' "${minimum}" "${candidate}" | sort -V | tail -n 1)"
	[[ "${newest}" == "${candidate}" ]]
}

[[ "${base_arch}" =~ ^[A-Za-z0-9_]+$ ]] || {
	echo "Invalid base kernel release architecture: ${base_release}" >&2
	exit 1
}

case "${profile}" in
	dale|dell-xps-9350-intel|base-dell-xps-9350-intel|sales-dell-xps-9350-intel|support-dell-xps-9350-intel)
		if [[ -n "${PURPLEFIN_DELL_IPU7_KERNEL_EVR:-}" ]]; then
			printf '%s.%s\n' "${PURPLEFIN_DELL_IPU7_KERNEL_EVR#0:}" "${base_arch}"
		elif [[ "${PURPLEFIN_DELL_IPU7_KERNEL_ALLOW_UNPINNED:-0}" == "1" ]]; then
			echo 'An unpinned Dell kernel build must set PURPLEFIN_OSTREE_LINUX explicitly' >&2
			exit 1
		elif version_at_least "${base_version}" "${minimum_version}"; then
			printf '%s\n' "${base_release}"
		else
			printf '%s.%s\n' "${pinned_evr#0:}" "${base_arch}"
		fi
		;;
	dell-xps-9350-intel-no-ipu7)
		printf '%s.%s\n' "${PURPLEFIN_DELL_MAINLINE_KERNEL_EVR:-${pinned_evr}}" "${base_arch}"
		;;
	base-generic|sales-generic|support-generic|developer-generic|trainer-generic|executive-generic|it-generic|generic-x86_64|desktop-x86_64|lenovo-generic)
		printf '%s\n' "${base_release}"
		;;
	*)
		echo "Unknown Purplefin build profile: ${profile}" >&2
		exit 2
		;;
esac
