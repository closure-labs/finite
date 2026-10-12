#!/usr/bin/env bash
# Run as root inside the acceptance VM; assert storage, not just crypttab intent.
set -euo pipefail
for path in /sysroot /var; do
  # Btrfs mounts can expose anonymous 0:N device IDs. Resolve their actual
  # backing source and remove findmnt's optional subvolume suffix instead.
  device=$(findmnt -n -o SOURCE --target "$path")
  device=${device%%\[*}
  [[ $device == /dev/* ]]
  topology=$(lsblk --inverse --json --output NAME,TYPE "$device")
  printf '%s\n' "$topology"
  mappings=$(jq -er '[.. | objects | select(.type? == "crypt") | .name] | if length > 0 then .[] else error("unencrypted backing device") end' <<<"$topology")
  while IFS= read -r mapping; do
    cryptsetup status "$mapping" | grep -E 'type:[[:space:]]+LUKS[12]$'
  done <<<"$mappings"
done
