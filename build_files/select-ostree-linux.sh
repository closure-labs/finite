#!/usr/bin/env bash
set -euo pipefail

profile="${1:?usage: select-ostree-linux.sh PROFILE BASE_KERNEL_RELEASE}"
base_release="${2:?usage: select-ostree-linux.sh PROFILE BASE_KERNEL_RELEASE}"
base_arch="${base_release##*.}"

[[ "${base_arch}" =~ ^[A-Za-z0-9_]+$ ]] || {
	echo "Invalid base kernel release architecture: ${base_release}" >&2
	exit 1
}

case "${profile}" in
	dale | \
	base-dell-xps-9350-intel | \
	sales-dell-xps-9350-intel | \
	support-dell-xps-9350-intel | \
	base-generic | \
	sales-generic | \
	support-generic | \
	developer-generic | \
	trainer-generic | \
	executive-generic | \
	it-generic)
		printf '%s\n' "${base_release}"
		;;
	*)
		echo "Unknown Purplefin build profile: ${profile}" >&2
		exit 2
		;;
esac
