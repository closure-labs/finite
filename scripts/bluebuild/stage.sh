#!/usr/bin/env bash
set -euo pipefail
profile="${1:?recipe profile is required}"
case "$profile" in
bluefin-generic|bluefin-dx-generic) output=image-payload ;;
*) echo "Unknown image profile: $profile" >&2; exit 2 ;;
esac
payload=$(nix build --accept-flake-config --no-link --print-out-paths ".#$output")
test -d "$payload/home-manager-template"
rm -rf files/payload
mkdir -p files/payload
cp -a "$payload/." files/payload/
chmod -R u+w files/payload
