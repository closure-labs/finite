#!/usr/bin/env bash
# Installed only in the acceptance VM; serial output remains available without SSH.
set -uo pipefail
echo 'BEGIN Finite VM authentication diagnostics'
date -u
getent passwd finite-test
id finite-test
passwd -S finite-test
sshd -T -C user=finite-test,host=bluefin,addr=10.0.2.2 | \
  grep -E '^(authorizedkeys|authentication|pubkey|usepam|allowusers|allowgroups|denyusers|denygroups)'
home=$(getent passwd finite-test | cut -d: -f6)
if [[ -n $home ]]; then
  for path in "$home" "$home/.ssh" "$home/.ssh/authorized_keys"; do
    ls -ldZ "$path"
  done
  ssh-keygen -lf "$home/.ssh/authorized_keys"
fi
systemctl --no-pager --full status finite-vm-user-labels sshd cloud-init-local cloud-init cloud-config cloud-final
journalctl --no-pager -b -u finite-vm-user-labels -u sshd -u cloud-init-local -u cloud-init -u cloud-config -u cloud-final -n 150
echo 'END Finite VM authentication diagnostics'
