#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../.." && pwd)
aspect_root="${repo_root}/modules/aspects/hardware/next-x86_64"
lock="${repo_root}/sources/kernel-next.json"

test -x "${aspect_root}/apply.sh"
test -f "${aspect_root}/default.nix"
jq -e '
  .schema == 1 and
  .release == "7.2.0-61.fc45.x86_64" and
  (.packages | map(.name)) == [
    "kernel", "kernel-core", "kernel-modules-core", "kernel-modules", "kernel-modules-extra"
  ] and
  (.requiredModules | sort) == [
    "intel_cvs", "intel_ipu7", "intel_ipu7_isys", "ipu_bridge", "ov02c10"
  ]
' "${lock}" >/dev/null
grep -qF 'hardware-next-x86_64' "${aspect_root}/default.nix"
grep -qF '../../../../sources/kernel-next.json' "${aspect_root}/default.nix"
grep -qF 'sha256sum --check --strict' "${aspect_root}/apply.sh"
# shellcheck disable=SC2016
grep -qF 'dnf5 -y install --allowerasing "${rpms[@]}"' "${aspect_root}/apply.sh"
grep -qF 'finite_apply_hardware_security next-x86_64' "${aspect_root}/apply.sh"
if rg -n 'curl|git clone|kernel-devel.*install|libcamera|hm1092|updates/finite' \
	"${aspect_root}/apply.sh" "${aspect_root}/default.nix"; then
	echo 'The next-kernel aspect contains an external module or userspace camera build' >&2
	exit 1
fi
