#!/usr/bin/env bash
repo_root="${PURPLEFIN_SOURCE_ROOT:-$PWD}"
[[ -f "${repo_root}/flake.nix" ]] || {
  echo "Run this command from the Purplefin repository root" >&2
  exit 2
}
(( $# == 2 )) || {
  echo "usage: nix run .#image-build -- PROFILE IMAGE_TAG" >&2
  exit 2
}
cd "${repo_root}" || exit
profile="$1"
tag="$2"
jq -e --arg profile "${profile}" '.profiles[$profile]' \
  "${PURPLEFIN_GENERATED_ROOT:?}/bootc/generated/profile-catalog.json" >/dev/null || {
  echo "Unknown profile: ${profile}" >&2
  exit 2
}
base_image="$("${PURPLEFIN_LOAD_BLUEFIN:?}")"
exec podman build \
  --file bootc/Containerfile \
  --network host \
  --pull=never \
  --security-opt label=disable \
  --build-context "purplefin-generated=${PURPLEFIN_GENERATED_ROOT}" \
  --build-arg "BASE_REF=${base_image}" \
  --build-arg "BUILD_PROFILE=${profile}" \
  --build-arg "PURPLEFIN_VERSION=${PURPLEFIN_VERSION:?}" \
  --label "org.opencontainers.image.base.digest=${PURPLEFIN_BASE_DIGEST:?}" \
  --tag "${tag}" \
.
