#!/usr/bin/env bash
set -euo pipefail

aspect_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
provisioner="${aspect_root}/rootfs/usr/libexec/finite/provision-determinate-nix"
test_root="$(mktemp -d)"
trap 'rm -rf -- "${test_root}"' EXIT
seed="${test_root}/seed"
state="${test_root}/var/home/nix"

install -d "${seed}/store" "${seed}/var/nix" "${test_root}/bin"
printf '%s\n' '{}' >"${seed}/receipt.json"
printf '%s\n' '#!/usr/bin/env bash' 'exit 0' >"${seed}/nix-installer"
chmod 0755 "${seed}/nix-installer"
printf '#!%s\nexit 0\n' "$(type -P bash)" >"${test_root}/bin/restorecon"
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
