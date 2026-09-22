#!/usr/bin/env bash
set -euo pipefail
profile="${1:?profile required}"
publish="${2:-false}"
case "$profile" in
  bluefin-generic|bluefin-next|bluefin-dx-generic|bluefin-dx-next) ;;
  *) echo "Unknown image profile: $profile" >&2; exit 1 ;;
esac
case "$publish" in
  true|false) ;;
  *) echo "Publish must be true or false" >&2; exit 1 ;;
esac

# Use the CLI installed from sources/bluebuild-cli.json and the flake's cosign.
# Explicit flags avoid clap's surprising treatment of false boolean env values.
unset BB_BUILD_PUSH BB_BUILD_NO_SIGN BB_SQUASH BB_BUILD_CHUNKAH BB_BUILD_CHUNKED_OCI BB_BUILD_RECHUNK
args=(build -v --build-driver docker --run-driver docker --signing-driver cosign
  --registry ghcr.io --registry-namespace closure-labs --cache-layers)
if [[ $publish == true ]]; then
  : "${BB_USERNAME:?registry username required}" "${BB_PASSWORD:?registry token required}"
  : "${COSIGN_PRIVATE_KEY:?publication signing key required}"
  # BlueBuild logs Docker and cosign in using stdin, checks the signing key
  # against cosign.pub, then signs and verifies the pushed image. Remove the
  # persisted registry login even if building, pushing or signing fails.
  trap 'docker logout ghcr.io >/dev/null 2>&1 || true' EXIT
  args+=(--push --retry-push --retry-count 3)
else
  unset COSIGN_PRIVATE_KEY
fi
bluebuild "${args[@]}" "recipes/$profile.yml"
