#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
provisioner="${repo_root}/files/system/usr/libexec/finite/provision-determinate-nix"
test_root="$(mktemp -d)"
trap 'rm -rf -- "${test_root}"' EXIT
seed="${test_root}/seed"
state="${test_root}/var/home/nix"

install -d "${seed}/store/fixture/etc" "${seed}/var/nix" "${test_root}/bin"
printf '%s\n' '{}' >"${seed}/receipt.json"
printf '%s\n' '#!/usr/bin/env bash' 'exit 0' >"${seed}/nix-installer"
chmod 0755 "${seed}/nix-installer"
export RESTORECON_CALLS="${test_root}/restorecon.calls"
printf '#!%s\nprintf "%%s\\n" "$*" >>"$RESTORECON_CALLS"\nif [[ $1 == -RFD ]]; then exit "${RESTORECON_STATUS:-0}"; fi\n' \
	"$(type -P bash)" >"${test_root}/bin/restorecon"
chmod 0755 "${test_root}/bin/restorecon"

PATH="${test_root}/bin:${PATH}" \
	FINITE_NIX_SEED_ROOT="${seed}" \
	FINITE_NIX_STATE_ROOT="${state}" \
	bash "${provisioner}"
test -x "${state}/nix-installer"
test -d "${state}/store"
printf '%s\n' preserved >"${state}/user-state"

PATH="${test_root}/bin:${PATH}" \
	FINITE_NIX_SEED_ROOT="${seed}" \
	FINITE_NIX_STATE_ROOT="${state}" \
	bash "${provisioner}"
grep -qx preserved "${state}/user-state"

# Both initial provisioning and repeat boots check mutable state while allowing
# SELinux's policy-aware digest cache to avoid rescanning the store contents.
printf '%s\n' "-RF -e ${state}/store ${state}" "-F ${state}/store" "-RFD ${state}/store/fixture" \
	"-RF -e ${state}/store ${state}" "-F ${state}/store" "-RFD ${state}/store/fixture" >"${test_root}/expected.calls"
[[ $(cat "${test_root}/expected.calls") == "$(cat "$RESTORECON_CALLS")" ]]

# A new store path must reach restorecon even after a previous successful boot.
install -d "${state}/store/new-package/bin"
: >"$RESTORECON_CALLS"
PATH="${test_root}/bin:${PATH}" \
	FINITE_NIX_SEED_ROOT="${seed}" FINITE_NIX_STATE_ROOT="${state}" \
	bash "${provisioner}"
grep '^-RFD ' "$RESTORECON_CALLS" | grep -qF "${state}/store/new-package"

# A batched store relabel failure must still block Nix startup.
if PATH="${test_root}/bin:${PATH}" RESTORECON_STATUS=1 \
	FINITE_NIX_SEED_ROOT="${seed}" FINITE_NIX_STATE_ROOT="${state}" \
	bash "${provisioner}"; then
	echo 'SELinux relabel failure was ignored' >&2
	exit 1
fi

malformed="${test_root}/var/home/malformed"
install -d "${malformed}"
printf '%s\n' partial >"${malformed}/unexpected"
if PATH="${test_root}/bin:${PATH}" \
	FINITE_NIX_SEED_ROOT="${seed}" \
	FINITE_NIX_STATE_ROOT="${malformed}" \
	bash "${provisioner}" >/dev/null 2>&1; then
	echo 'Malformed Determinate Nix state was unexpectedly replaced' >&2
	exit 1
fi
grep -qx partial "${malformed}/unexpected"
