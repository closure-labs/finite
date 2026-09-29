#!/usr/bin/env bash
# Run inside the guest as root; verify actual enrollment, not versioned test-key status.
set -euo pipefail
expected="${1:?expected certificate SHA-256 required}"
[[ $expected =~ ^[0-9a-f]{64}$ ]]
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cd "$work"
mokutil --version
mokutil --export
shopt -s nullglob
for certificate in MOK-*.der; do
  actual=$(sha256sum "$certificate")
  if [[ ${actual%% *} == "$expected" ]]; then
    printf 'Enrolled MOK certificate SHA-256: %s\n' "$expected"
    exit 0
  fi
done
echo "Expected certificate is absent from enrolled MOKs: $expected" >&2
exit 1
