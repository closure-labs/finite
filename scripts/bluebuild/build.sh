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

# Nix shells export a reproducible epoch (1980-01-01). Buildx inherits it
# into the image's creation time, making bootc/rpm-ostree reject upgrades.
# OS images need their actual build time; keep Nix payload builds reproducible.
unset SOURCE_DATE_EPOCH

# Use the CLI installed from sources/bluebuild-cli.json and the flake's cosign.
# Explicit flags avoid clap's surprising treatment of false boolean env values.
unset COSIGN_PRIVATE_KEY BB_BUILD_PUSH BB_BUILD_NO_SIGN BB_SQUASH BB_BUILD_CHUNKAH BB_BUILD_CHUNKED_OCI BB_BUILD_RECHUNK
args=(build -v --build-driver docker --run-driver docker --signing-driver cosign
  --registry ghcr.io --registry-namespace closure-labs --cache-layers --no-sign)
if [[ $publish == true ]]; then
  : "${BB_USERNAME:?registry username required}" "${BB_PASSWORD:?registry token required}"
  # Build and push an unsigned candidate. The isolated signing job runs only
  # after independent security checks; this job never receives its key.
  trap 'docker logout ghcr.io >/dev/null 2>&1 || true' EXIT
  args+=(--push --retry-push --retry-count 3)
fi
bluebuild "${args[@]}" "recipes/$profile.yml"
