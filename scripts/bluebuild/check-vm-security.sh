#!/usr/bin/env bash
# Read-only assertions for the candidate VM, with hostile NoCloud media attached.
# Historical predecessors/rollback images are not claimed to contain these fixes.
set -euo pipefail
test -n "$(blkid -L cidata)"
[[ $(getenforce) == Enforcing ]]
test -f /etc/cloud/cloud-init.disabled
yq -o=json '.' /etc/cloud/cloud.cfg.d/90-finite-nocloud.cfg | jq -se 'length == 1 and .[0].datasource_list == ["None"]' >/dev/null
for unit in cloud-init-local.service cloud-init.service cloud-config.service cloud-final.service; do
  [[ $(systemctl show "$unit" -p ActiveState --value) == inactive ]]
done
# Check both the file-writing and command-execution paths in the attached seed.
test ! -e /var/lib/finite-nocloud-write-executed
test ! -e /var/lib/finite-nocloud-command-executed
modules=$(semodule -l)
awk '$1 == "nix" { found = 1 } END { exit !found }' <<<"$modules"
systemctl is-active --quiet finite-nix-selinux.service
printf 'Candidate SELinux enforcing; Nix policy active; NoCloud media rejected\n'
