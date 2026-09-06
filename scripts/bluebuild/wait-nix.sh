#!/usr/bin/env bash
# SSH can become available while the first-boot SELinux policy is still compiling.
set -euo pipefail
units=(finite-nix-selinux.service finite-nix-seed.service nix.mount
  nix-daemon.socket determinate-nixd.socket)
deadline=$((SECONDS + 180))
while :; do
  ready=true
  for unit in "${units[@]}"; do
    systemctl is-active --quiet "$unit" || ready=false
  done
  if [[ $ready == true ]]; then
    echo 'All Nix initialization units and daemon sockets are active'
    exit 0
  fi
  if systemctl is-failed --quiet "${units[@]}" || ((SECONDS >= deadline)); then
    echo 'Nix initialization failed or did not finish within three minutes' >&2
    systemctl --no-pager --full status "${units[@]}" || true
    journalctl --no-pager -b -u finite-nix-selinux -u finite-nix-seed \
      -u nix.mount -u nix-daemon -u determinate-nixd
    exit 1
  fi
  sleep 2
done
