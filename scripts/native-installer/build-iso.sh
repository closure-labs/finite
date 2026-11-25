#!/usr/bin/env bash
# Build the Finite native installer ISO for one verified native image digest.
# Usage: build-iso.sh REPOSITORY TAG DIGEST
#   e.g. build-iso.sh ghcr.io/closure-labs/finite finite-native sha256:<64 hex>
# Runs on the ephemeral hosted ISO runner (root podman); never on a workstation.
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} == true && ${GITHUB_REPOSITORY:-} == closure-labs/finite ]] || {
  echo 'Build native installer media only on the ephemeral Finite ISO runner.' >&2
  exit 2
}
repository=${1:?repository}
tag=${2:?tag}
digest=${3:?digest}
[[ $repository =~ ^ghcr\.io/closure-labs/finite$ ]] || { echo "Unexpected repository $repository" >&2; exit 2; }
[[ $tag == finite-native || $tag == finite-native-dev ]] || { echo 'Invalid tag' >&2; exit 2; }
[[ $digest =~ ^sha256:[0-9a-f]{64}$ ]] || { echo 'Digest must be immutable' >&2; exit 2; }
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/../.." && pwd)
lock="$root/sources/native-installer.json"
builder="$(jq -er '.imageBuilder.image' "$lock")@$(jq -er '.imageBuilder.digest' "$lock")"
[[ $builder =~ ^ghcr\.io/osbuild/image-builder-cli@sha256:[0-9a-f]{64}$ ]]
[[ $(jq -er .imageBuilder.imageType "$lock") == generic-iso ]]
output=${ISO_OUTPUT_DIR:-$root/.bluebuild/native-iso}
installer="localhost/finite-native-installer:$tag"
payload="$repository:$tag"

# The payload must be the signed digest, stored under a tag: image-builder reads
# local containers-storage by name, and the installer targets that name.
cosign verify --new-bundle-format=false --key "$root/cosign.pub" "$repository@$digest" >/dev/null
sudo podman pull "$repository@$digest"
profile=$(sudo podman image inspect --format '{{index .Labels "io.finite.profile"}}' "$repository@$digest")
architecture=$(sudo podman image inspect --format '{{index .Labels "io.finite.boot-architecture"}}' "$repository@$digest")
[[ $profile == "$tag" && $architecture == native-composefs ]] || {
  echo 'Payload must be the matching native profile, authenticated by digest.' >&2; exit 2;
}
sudo podman tag "$repository@$digest" "$payload"
[[ $(sudo podman image inspect --format '{{.Digest}}' "$payload") == "$digest" ]]

sudo podman build --pull=never \
  --build-arg "PAYLOAD=$repository@$digest" --build-arg "PAYLOAD_REF=$payload" --build-arg "PAYLOAD_DIGEST=$digest" \
  --label "io.finite.native-installer.payload=$repository@$digest" \
  --tag "$installer" "$here"
sudo podman pull "$builder"

mkdir -p "$output"
sudo podman run --rm --privileged --security-opt label=type:unconfined_t \
  -v /var/lib/containers/storage:/var/lib/containers/storage \
  -v "$output":/output \
  "$builder" build --output-dir /output \
  --bootc-ref "$installer" --bootc-installer-payload-ref "$payload" --bootc-default-fs ext4 \
  generic-iso
sudo chown -R "$(id -u):$(id -g)" "$output"

mapfile -t isos < <(find "$output" -type f -name '*.iso')
[[ ${#isos[@]} == 1 ]] || { echo "Expected one ISO, found ${#isos[@]}" >&2; exit 1; }
final="$output/finite-native-installer-$tag.iso"
[[ ${isos[0]} == "$final" ]] || mv "${isos[0]}" "$final"
installer_id=$(sudo podman image inspect --format '{{.Id}}' "$installer")
jq -n --arg payload "$repository@$digest" --arg tag "$payload" --arg installer "$installer_id" \
  --arg builder "$builder" --arg revision "${GITHUB_SHA:?}" \
  '{schema: 1, payload: $payload, payloadTag: $tag, installerImageId: $installer,
    imageBuilder: $builder, finiteRevision: $revision}' >"$output/installation.json"
(cd "$output" && sha256sum -- "$(basename "$final")" installation.json >SHA256SUMS)
echo "Native installer ISO: $final"
