#!/usr/bin/env bash
set -euo pipefail
authselect check
read -r -a inherited <<<"$(authselect current --raw)"
[[ ${#inherited[@]} -gt 0 && ${inherited[0]} =~ ^[a-zA-Z0-9][a-zA-Z0-9_/-]*$ ]]
profile=${inherited[0]}
available=$(authselect list-features "$profile")
pending=()
for feature in with-silent-lastlog with-mdns4 with-fingerprint with-pam-u2f; do
  if [[ " ${inherited[*]} " == *" $feature "* ]]; then continue; fi
  if ! grep -Eq "^[[:space:]]*(-[[:space:]]+)?${feature}[[:space:]]*$" <<<"$available"; then
    echo "Upstream authselect profile does not support required feature: $feature" >&2
    exit 1
  fi
  pending+=("$feature")
done
for feature in "${pending[@]}"; do
  authselect enable-feature "$feature"
done
authselect check
read -r -a retained <<<"$(authselect current --raw)"
[[ ${retained[0]} == "$profile" ]]
for feature in "${inherited[@]:1}"; do
  [[ " ${retained[*]} " == *" $feature "* ]]
done
