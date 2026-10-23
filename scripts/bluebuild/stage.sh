#!/usr/bin/env bash
set -euo pipefail
profile="${1:?recipe profile is required}"
case "$profile" in
finite|finite-dev) ;;
*) echo "Unknown image profile: $profile" >&2; exit 2 ;;
esac
payload=$(nix build --impure --accept-flake-config --no-update-lock-file --no-write-lock-file \
  --file lib/ci-payload.nix payload --no-link --print-out-paths)
test -d "$payload/home-manager-template"
rm -rf files/payload
mkdir -p files/payload
cp -a "$payload/." files/payload/
chmod -R u+w files/payload
