#!/usr/bin/env bash
set -euo pipefail
channel="${1:?update channel required}"
digest="${2:?verified image digest required}"
case "$channel" in
finite|latest|finite-dev) ;;
*) echo 'Unsupported update channel' >&2; exit 2 ;;
esac
[[ $digest =~ ^sha256:[0-9a-f]{64}$ ]]
export ISO_OUTPUT_DIR="${ISO_OUTPUT_DIR:-.bluebuild/iso}"
repository=ghcr.io/closure-labs/finite
source="$repository@$digest"
mkdir -p "$ISO_OUTPUT_DIR"
cosign verify --new-bundle-format=false --key cosign.pub "$source" >"$ISO_OUTPUT_DIR"/signature.json
# Lorax uses finite-x86_64-TAG as the ISO volume ID (at most 32 bytes).
# Keep 64 random bits plus a prefix; reject any existing tag before copying.
tag="i$(printf '%s-%s-%s' "${GITHUB_RUN_ID:?}" "${GITHUB_RUN_ATTEMPT:?}" \
  "$(cat /proc/sys/kernel/random/uuid)" | sha256sum | cut -c1-16)"
volume_id="finite-x86_64-$tag"
[[ ${#volume_id} -le 32 ]]
# List must succeed: authentication/transport errors are not proof of absence.
skopeo list-tags "docker://$repository" >"$ISO_OUTPUT_DIR"/tags.json
jq -e --arg tag "$tag" '.Tags | index($tag) == null' "$ISO_OUTPUT_DIR"/tags.json >/dev/null
# Inspect the verified digest, not a channel that daily builds may have advanced.
skopeo inspect "docker://$source" >"$ISO_OUTPUT_DIR"/source.json
[[ $(jq -r .Digest "$ISO_OUTPUT_DIR"/source.json) == "$digest" ]]
profile=$(jq -er '.Labels["io.finite.profile"]' "$ISO_OUTPUT_DIR"/source.json)
case "$channel:$profile" in
finite:finite|latest:finite|finite-dev:finite-dev) ;;
finite:bluefin-generic|finite-dev:bluefin-dx-generic)
  # Only the exact published predecessor may retain its historical profile.
  # Keep that value in installation.json; never relabel its signed image.
  [[ ${FINITE_PREDECESSOR_DIGEST:-} == "$digest" && ${PROFILE:-} == "$channel" ]] || {
    echo 'Historical image profiles are permitted only for the exact upgrade predecessor' >&2
    exit 1
  }
  ;;
*) echo 'Image profile does not match the requested channel' >&2; exit 1 ;;
esac
bash "$(dirname "${BASH_SOURCE[0]}")/prepare-installer.sh"
iso_started=$SECONDS
skopeo copy --all --preserve-digests "docker://$source" "docker://$repository:$tag"
[[ $(skopeo inspect --format '{{.Digest}}' "docker://$repository:$tag") == "$digest" ]]
cosign verify --new-bundle-format=false --key cosign.pub "$repository:$tag" >/dev/null
jq -n --arg image "$source" --arg tag "$repository:$tag" \
  --arg channel "$repository:$channel" --arg profile "$profile" \
  --slurpfile installer "$ISO_OUTPUT_DIR"/installer.json \
  '{image: $image, installationTag: $tag, updateChannel: $channel, profile: $profile,
    installer: $installer[0]}' \
  >"$ISO_OUTPUT_DIR"/installation.json
# v0.9.37 constructs IMAGE_TAG from a tag; a digest-only reference becomes latest.
sudo bluebuild generate-iso --run-driver docker --variant kinoite --output-dir "$ISO_OUTPUT_DIR" \
  --iso-name "${channel/latest/finite}.iso" image "$repository:$tag"
# Confirm that the install source tag has not changed while the ISO was assembled.
[[ $(skopeo inspect --format '{{.Digest}}' "docker://$repository:$tag") == "$digest" ]]
(cd "$ISO_OUTPUT_DIR" && sha256sum -- *.iso installation.json >SHA256SUMS)

printf "ISO generation completed in %s seconds\n" "$((SECONDS - iso_started))"
