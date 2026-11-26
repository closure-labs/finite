#!/usr/bin/env bash
# Build the Finite native installer ISO for one verified native image digest.
# Usage: build-iso.sh REPOSITORY TAG DIGEST [SEALED_VALIDATION_ARCHIVE SEAL_RECEIPT]
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
validation_archive=${4:-}
validation_receipt=${5:-}
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
revision=${GITHUB_SHA:?}
[[ $revision =~ ^[0-9a-f]{40}$ ]]
[[ ! -e $output ]] || { echo 'Use a fresh ISO output directory.' >&2; exit 2; }
cache=$(mktemp -d "${RUNNER_TEMP:?}/native-osbuild.XXXXXXXX")
trap 'sudo rm -rf -- "$cache"' EXIT

# Both paths require an immutable manifest before building a derived live root.
# Only the dedicated validation run accepts an archive sealed with a VM key.
validation=false
if [[ -n $validation_archive || -n $validation_receipt ]]; then
  [[ (${GITHUB_REF:-} == refs/heads/qualification/native-iso ||
       ${GITHUB_REF:-} == refs/heads/qualification/native-lifecycle) && $# == 5 ]]
  # The hosted validator transfers ownership of its fresh temporary archive.
  [[ $validation_archive == "${RUNNER_TEMP:?}"/native-iso.????????/sealed.oci.tar ]]
  [[ -f $validation_archive && $(realpath -- "$validation_archive") == "$validation_archive" ]]
  archive_hash=$(sha256sum -- "$validation_archive" | cut -d' ' -f1)
  jq -e --arg sha "$archive_hash" --arg profile "$tag" --arg revision "$revision" '
    .schema == 1 and .validationOnly == true and .archiveSha256 == $sha and
    .profile == $profile and .sourceRevision == $revision and .integrity.strictVerity == true and
    .integrity.archiveSha256 == $sha and .integrity.bootableRootDigest == .bootableRootDigest
  ' "$validation_receipt" >/dev/null
  payload_archive=$validation_archive
  validation=true
else
  [[ ${GITHUB_REF:-} == refs/heads/main && $# == 3 ]]
  cosign verify --new-bundle-format=false --key "$root/cosign.pub" "$repository@$digest" >/dev/null
  payload_archive="$cache/payload.oci.tar"
  skopeo copy --preserve-digests "docker://$repository@$digest" "oci-archive:$payload_archive"
fi
sudo skopeo copy --preserve-digests "oci-archive:$payload_archive" "containers-storage:$payload"
[[ $(sudo podman image inspect --format '{{.Digest}}' "$payload") == "$digest" ]]
profile=$(sudo podman image inspect --format '{{index .Labels "io.finite.profile"}}' "$payload")
architecture=$(sudo podman image inspect --format '{{index .Labels "io.finite.boot-architecture"}}' "$payload")
[[ $profile == "$tag" && $architecture == native-composefs ]] || {
  echo 'Payload must be the matching native profile, authenticated by digest.' >&2; exit 2;
}
sudo podman build --pull=never \
  --build-arg "PAYLOAD=$payload" --build-arg "PAYLOAD_REF=$payload" --build-arg "PAYLOAD_DIGEST=$digest" \
  --build-arg "VALIDATION=$validation" \
  --volume "$payload_archive:/run/finite-payload.oci.tar:ro" \
  --label "io.finite.native-installer.payload=$repository@$digest" \
  --tag "$installer" "$here"
rm -- "$payload_archive"
sudo podman pull "$builder"

mkdir -p "$output"
df -h -- "$cache" "$output"
sudo podman run --rm --privileged --security-opt label=disable \
  -v /var/lib/containers/storage:/var/lib/containers/storage \
  -v "$output":/output \
  -v "$cache":/osbuild-cache \
  "$builder" build --output-dir /output --cache /osbuild-cache \
  --bootc-ref "$installer" --bootc-default-fs ext4 \
  generic-iso
sudo chown -R "$(id -u):$(id -g)" "$output"

mapfile -t isos < <(find "$output" -type f -name '*.iso')
[[ ${#isos[@]} == 1 ]] || { echo "Expected one ISO, found ${#isos[@]}" >&2; exit 1; }
final="$output/finite-native-installer-$tag.iso"
[[ ${isos[0]} == "$final" ]] || mv "${isos[0]}" "$final"
installer_id=$(sudo podman image inspect --format '{{.Id}}' "$installer")
jq -n --arg payload "$repository@$digest" --arg tag "$payload" --arg installer "$installer_id" \
  --arg builder "$builder" --arg revision "$revision" --argjson validation "$validation" \
  '{schema: 1, payload: $payload, payloadTag: $tag, installerImageId: $installer,
    imageBuilder: $builder, finiteRevision: $revision, validationOnly: $validation}' >"$output/installation.json"
(cd "$output" && sha256sum -- "$(basename "$final")" installation.json >SHA256SUMS)
echo "Native installer ISO: $final"
