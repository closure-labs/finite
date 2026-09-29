#!/usr/bin/env bash
set -euo pipefail

home=/home/finite-test
restorecon -RF "$home"
matchpathcon -V "$home" "$home/.ssh" "$home/.ssh/authorized_keys"
for entry in "$home:user_home_dir_t" "$home/.ssh:ssh_home_t" "$home/.ssh/authorized_keys:ssh_home_t"; do
  path=${entry%:*}
  expected=${entry##*:}
  actual=$(stat -c '%C' "$path")
  if [[ $actual != *":$expected:"* ]]; then
    printf 'Unexpected SELinux context for %s: %s (expected %s)\n' "$path" "$actual" "$expected" >&2
    exit 1
  fi
done
ls -ldZ "$home" "$home/.ssh" "$home/.ssh/authorized_keys"
