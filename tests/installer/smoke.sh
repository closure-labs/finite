#!/usr/bin/env bash
set -euo pipefail

installer_smoke="${1:?usage: smoke.sh INSTALLER_SMOKE}"
test_root="$(mktemp -d)"
trap 'rm -rf -- "${test_root}"' EXIT

touch "${test_root}/flake.nix"
printf 'iso\n' >"${test_root}/installer.iso"

printf '#!%s\n' "$(command -v bash)" >"${test_root}/qemu-img"
cat >>"${test_root}/qemu-img" <<'EOF'
set -euo pipefail
touch "${@: -2:1}"
EOF
chmod +x "${test_root}/qemu-img"

run_smoke() {
	FINITE_SOURCE_ROOT="${test_root}" \
		FINITE_QEMU_IMG="${test_root}/qemu-img" \
		FINITE_QEMU="${test_root}/qemu" \
		FINITE_INSTALLER_SMOKE_TIMEOUT_SECONDS=1 \
		FINITE_INSTALLER_SMOKE_POLL_INTERVAL_SECONDS=0.05 \
		"${installer_smoke}" "${test_root}/installer.iso"
}

printf '#!%s\n' "$(command -v bash)" >"${test_root}/qemu"
cat >>"${test_root}/qemu" <<'EOF'
trap 'exit 143' TERM
echo 'Starting graphical live session'
sleep 30 &
wait $!
EOF
chmod +x "${test_root}/qemu"

if run_smoke; then
	echo 'Smoke test accepted a generic live-session boot message' >&2
	exit 1
fi

printf '#!%s\n' "$(command -v bash)" >"${test_root}/qemu"
cat >>"${test_root}/qemu" <<'EOF'
trap 'exit 143' TERM
echo 'FINITE_INSTALLER_READY=1'
sleep 30 &
wait $!
EOF
chmod +x "${test_root}/qemu"

started="${SECONDS}"
run_smoke
((SECONDS - started < 5))
grep -qF 'FINITE_INSTALLER_READY=1' "${test_root}/qemu-boot.log"

printf '#!%s\n' "$(command -v bash)" >"${test_root}/qemu"
cat >>"${test_root}/qemu" <<'EOF'
trap 'exit 143' TERM
echo 'FINITE_INSTALLER_ERROR=bootc-installer log-not-created'
sleep 30 &
wait $!
EOF
chmod +x "${test_root}/qemu"

if run_smoke; then
	echo 'Smoke test accepted an installer launcher failure marker' >&2
	exit 1
fi

printf '#!%s\n' "$(command -v bash)" >"${test_root}/qemu"
cat >>"${test_root}/qemu" <<'EOF'
echo 'Firmware initialized'
EOF
chmod +x "${test_root}/qemu"

if run_smoke; then
	echo 'Smoke test accepted a boot without an installer-ready marker' >&2
	exit 1
fi

printf '#!%s\n' "$(command -v bash)" >"${test_root}/qemu"
cat >>"${test_root}/qemu" <<'EOF'
exit 42
EOF
chmod +x "${test_root}/qemu"

set +e
run_smoke
status=$?
set -e
[[ "${status}" == 42 ]]
