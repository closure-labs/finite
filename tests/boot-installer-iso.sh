#!/usr/bin/env bash
set -euo pipefail

iso="${1:?usage: boot-installer-iso.sh ISO}"
[[ -s "${iso}" ]] || { echo "Installer ISO is missing: ${iso}" >&2; exit 2; }
command -v qemu-system-x86_64 >/dev/null

log="$(dirname -- "${iso}")/qemu-boot.log"
disk="$(mktemp --suffix=.qcow2)"
trap 'rm -f -- "${disk}"' EXIT
qemu-img create -q -f qcow2 "${disk}" 32G

acceleration=(-accel "tcg,thread=multi")
if [[ -r /dev/kvm && -w /dev/kvm ]]; then
	acceleration=(-accel kvm)
fi

set +e
timeout --signal=TERM 5m \
	qemu-system-x86_64 \
		"${acceleration[@]}" \
		-machine q35 \
		-m 4096 \
		-smp 2 \
		-drive "file=${disk},if=virtio,format=qcow2" \
		-cdrom "${iso}" \
		-boot d \
		-display none \
		-serial stdio \
		-no-reboot 2>&1 | tee "${log}"
qemu_status="${PIPESTATUS[0]}"
set -e

case "${qemu_status}" in
	0 | 124 | 143) ;;
	*) echo "QEMU failed with status ${qemu_status}" >&2; exit "${qemu_status}" ;;
esac

grep -Eqi 'anaconda|installation.*started|starting.*installer' "${log}" || {
	echo 'The ISO booted but did not reach the Anaconda installer' >&2
	exit 1
}
