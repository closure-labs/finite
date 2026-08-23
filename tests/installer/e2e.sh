#!/usr/bin/env bash
set -euo pipefail

installer_e2e="${1:?usage: e2e.sh INSTALLER_E2E}"
test_root="$(mktemp -d)"
trap 'rm -rf -- "${test_root}"' EXIT

printf 'iso\n' >"${test_root}/installer.iso"
payload_digest='sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
update_reference='ghcr.io/example/finite:bluefin-generic'
sed \
	-e "s|@@INSTALLER_PAYLOAD_SOURCE_REF@@|${update_reference}|g" \
	-e "s|@@INSTALLER_PAYLOAD_TARGET_REF@@|${update_reference}|g" \
	-e "s|@@INSTALLER_PAYLOAD_DIGEST@@|${payload_digest}|g" \
	-e "s|@@INSTALLER_UPDATE_REFERENCE@@|${update_reference}|g" \
	installer/ci-unattended.ks.in >"${test_root}/installer.ks"

printf '#!%s\n' "$(command -v bash)" >"${test_root}/qemu-img"
cat >>"${test_root}/qemu-img" <<'EOF'
set -euo pipefail
printf 'qcow2\n' >"${@: -2:1}"
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
trap 'exit 143' TERM
echo "$$" >>"${FAKE_QEMU_PIDS}"
if [[ " $* " == *' -kernel '* ]]; then
	[[ " $* " == *' -initrd '* ]]
	kernel_arguments="${*: -1}"
	guest_url="${kernel_arguments##*inst.ks=}"
	host_url="${guest_url/10.0.2.2/127.0.0.1}"
	case "${FAKE_QEMU_MODE}" in
		missing-fetch)
			sleep 30 &
			wait $!
			;;
		install-timeout)
			python3 -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1]).read()' "${host_url}"
			echo 'Kickstart fetched; installation stalled'
			sleep 30 &
			wait $!
			;;
		install-failure)
			python3 -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1]).read()' "${host_url}"
			echo 'Installer failed after fetching Kickstart'
			exit 42
			;;
		success)
			python3 -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1]).read()' "${host_url}"
			echo 'Unattended installation complete'
			exit 0
			;;
		*) exit 2 ;;
	esac
fi

case "${FAKE_QEMU_MODE}" in
	boot-success)
		echo 'FINITE_INSTALLED_READY=1'
		sleep 30 &
		wait $!
		;;
	boot-wrong-digest)
		echo 'booted digest does not match the verified payload'
		exit 0
		;;
	boot-wrong-reference)
		echo 'booted image reference does not match the update channel'
		exit 0
		;;
	*) exit 2 ;;
esac
EOF
chmod +x "${test_root}/qemu"

run_e2e() {
	local mode=$1
	shift
	FAKE_QEMU_MODE="${mode}" \
		FAKE_QEMU_PIDS="${test_root}/qemu-pids" \
		FINITE_INSTALLER_DIAGNOSTICS_DIR="${test_root}/diagnostics" \
		FINITE_QEMU_IMG="${test_root}/qemu-img" \
		FINITE_QEMU="${test_root}/qemu" \
		FINITE_XORRISO="${test_root}/xorriso" \
		FINITE_INSTALLER_E2E_KICKSTART_TIMEOUT_SECONDS=3 \
		FINITE_INSTALLER_E2E_INSTALL_TIMEOUT_SECONDS=1 \
		FINITE_INSTALLER_E2E_BOOT_TIMEOUT_SECONDS=1 \
		FINITE_INSTALLER_SMOKE_POLL_INTERVAL_SECONDS=0.05 \
		"${installer_e2e}" "$@"
}

assert_status() {
	local expected=$1 mode=$2
	shift 2
	set +e
	run_e2e "${mode}" "$@" >"${test_root}/${mode}.out" 2>&1
	status=$?
	set -e
	[[ "${status}" == "${expected}" ]] || {
		cat "${test_root}/${mode}.out" >&2
		echo "${mode}: expected status ${expected}, got ${status}" >&2
		exit 1
	}
	grep -qF 'qemu-install.log' "${test_root}/${mode}.out"
	grep -qF 'qemu-kickstart-server.log' "${test_root}/${mode}.out"
}

assert_status 1 missing-fetch install \
	"${test_root}/installer.iso" "${test_root}/installer.ks" "${test_root}/missing-state"
assert_status 124 install-timeout install \
	"${test_root}/installer.iso" "${test_root}/installer.ks" "${test_root}/timeout-state"
assert_status 42 install-failure install \
	"${test_root}/installer.iso" "${test_root}/installer.ks" "${test_root}/failure-state"

success_state="${test_root}/success-state"
run_e2e success install \
	"${test_root}/installer.iso" "${test_root}/installer.ks" "${success_state}"
grep -qF 'Unattended installation complete' "${test_root}/diagnostics/qemu-install.log"
grep -qF '"GET /finite-ci.ks ' "${test_root}/diagnostics/qemu-kickstart-server.log"
run_e2e boot-success boot "${success_state}"
grep -qF 'FINITE_INSTALLED_READY=1' "${test_root}/diagnostics/qemu-installed-boot.log"

assert_status 1 boot-wrong-digest boot "${success_state}"
grep -qF 'qemu-installed-boot.log' "${test_root}/boot-wrong-digest.out"
assert_status 1 boot-wrong-reference boot "${success_state}"

while IFS= read -r pid; do
	if kill -0 "${pid}" >/dev/null 2>&1; then
		echo "QEMU process was not reaped: ${pid}" >&2
		exit 1
	fi
done <"${test_root}/qemu-pids"

ready_script="${test_root}/finite-ci-installed-ready"
awk '
	/^#!\/usr\/bin\/bash$/ { capture = 1 }
	/^FINITE_EOF$/ && capture { exit }
	capture { print }
' "${test_root}/installer.ks" >"${ready_script}"
chmod +x "${ready_script}"
printf '#!%s\n' "$(command -v bash)" >"${test_root}/bootc"
cat >>"${test_root}/bootc" <<'EOF'
set -euo pipefail
[[ "$*" == 'status --json --format-version=1' ]]
jq -n \
	--arg digest "${FAKE_BOOT_DIGEST}" \
	--arg reference "${FAKE_BOOT_REFERENCE}" \
	'{status:{booted:{image:{imageDigest:$digest,image:{image:$reference}}}}}'
EOF
chmod +x "${test_root}/bootc"

run_ready_script() {
	FAKE_BOOT_DIGEST=$1 \
		FAKE_BOOT_REFERENCE=$2 \
		FINITE_BOOTC="${test_root}/bootc" \
		FINITE_CONSOLE="${test_root}/console" \
		FINITE_PYTHON="$(command -v python3)" \
		bash "${ready_script}"
}

: >"${test_root}/console"
run_ready_script "${payload_digest}" "${update_reference}"
grep -qF "FINITE_INSTALLED_DIGEST=${payload_digest}" "${test_root}/console"
grep -qF "FINITE_INSTALLED_REFERENCE=${update_reference}" "${test_root}/console"
grep -qF 'FINITE_INSTALLED_READY=1' "${test_root}/console"

if run_ready_script 'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' "${update_reference}"; then
	echo 'Installed readiness accepted the wrong payload digest' >&2
	exit 1
fi
grep -qF 'FINITE_INSTALLED_ERROR=digest-mismatch' "${test_root}/console"
if grep -qF 'FINITE_INSTALLED_READY=1' "${test_root}/console"; then
	echo 'Installed readiness emitted success for the wrong payload digest' >&2
	exit 1
fi
if run_ready_script "${payload_digest}" 'ghcr.io/example/finite:wrong-channel'; then
	echo 'Installed readiness accepted the wrong update reference' >&2
	exit 1
fi
grep -qF 'FINITE_INSTALLED_ERROR=reference-mismatch' "${test_root}/console"
if grep -qF 'FINITE_INSTALLED_READY=1' "${test_root}/console"; then
	echo 'Installed readiness emitted success for the wrong update reference' >&2
	exit 1
fi
