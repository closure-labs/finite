#!/usr/bin/env bash
set -euo pipefail

installer_e2e="${1:?usage: e2e.sh INSTALLER_E2E}"
test_root="$(mktemp -d)"
trap 'rm -rf -- "${test_root}"' EXIT

printf 'iso\n' >"${test_root}/installer.iso"
printf 'text --non-interactive\n' >"${test_root}/installer.ks"
printf '#!%s\n' "$(command -v bash)" >"${test_root}/qemu-img"
cat >>"${test_root}/qemu-img" <<'EOF'
set -euo pipefail
touch "${@: -2:1}"
EOF
chmod +x "${test_root}/qemu-img"

printf '#!%s\n' "$(command -v bash)" >"${test_root}/xorriso"
cat >>"${test_root}/xorriso" <<'EOF'
set -euo pipefail
while (($#)); do
	if [[ "$1" == -extract ]]; then
		mkdir -p "$(dirname -- "$3")"
		printf 'boot artifact\n' >"$3"
		shift 3
	else
		shift
	fi
done
EOF
chmod +x "${test_root}/xorriso"

printf '#!%s\n' "$(command -v bash)" >"${test_root}/qemu"
cat >>"${test_root}/qemu" <<'EOF'
set -euo pipefail
if [[ " $* " == *' -kernel '* ]]; then
	[[ " $* " == *' -initrd '* ]]
	[[ " $* " == *' inst.ks=http://10.0.2.2:'* ]]
	echo 'Unattended installation complete'
	exit 0
fi
trap 'exit 143' TERM
echo 'PURPLEFIN_INSTALLED_READY=1'
sleep 30 &
wait $!
EOF
chmod +x "${test_root}/qemu"

PURPLEFIN_QEMU_IMG="${test_root}/qemu-img" \
	PURPLEFIN_QEMU="${test_root}/qemu" \
	PURPLEFIN_XORRISO="${test_root}/xorriso" \
	PURPLEFIN_INSTALLER_E2E_INSTALL_TIMEOUT_SECONDS=2 \
	PURPLEFIN_INSTALLER_E2E_BOOT_TIMEOUT_SECONDS=2 \
	PURPLEFIN_INSTALLER_SMOKE_POLL_INTERVAL_SECONDS=0.05 \
	"${installer_e2e}" "${test_root}/installer.iso" "${test_root}/installer.ks"

grep -qF 'Unattended installation complete' "${test_root}/qemu-install.log"
grep -qF 'PURPLEFIN_INSTALLED_READY=1' "${test_root}/qemu-installed-boot.log"
