#!/usr/bin/env bash
set -euo pipefail
channel="${1:?update channel required}"
digest="${2:?verified image digest required}"
case "$channel" in
bluefin-generic|latest|next|bluefin-dx-generic|dev-next) ;;
*) echo 'Unsupported update channel' >&2; exit 2 ;;
esac
[[ $digest =~ ^sha256:[0-9a-f]{64}$ ]]
repository=ghcr.io/closure-labs/finite
source="$repository@$digest"
mkdir -p .bluebuild/iso
cosign verify --key cosign.pub "$source" >.bluebuild/iso/signature.json
# Lorax uses finite-x86_64-TAG as the ISO volume ID (at most 32 bytes).
# Keep 64 random bits plus a prefix; reject any existing tag before copying.
tag="i$(printf '%s-%s-%s' "${GITHUB_RUN_ID:?}" "${GITHUB_RUN_ATTEMPT:?}" \
  "$(cat /proc/sys/kernel/random/uuid)" | sha256sum | cut -c1-16)"
volume_id="finite-x86_64-$tag"
[[ ${#volume_id} -le 32 ]]
# List must succeed: authentication/transport errors are not proof of absence.
skopeo list-tags "docker://$repository" >.bluebuild/iso/tags.json
jq -e --arg tag "$tag" '.Tags | index($tag) == null' .bluebuild/iso/tags.json >/dev/null
# Inspect the verified digest, not a channel that daily builds may have advanced.
skopeo inspect "docker://$source" >.bluebuild/iso/source.json
[[ $(jq -r .Digest .bluebuild/iso/source.json) == "$digest" ]]
profile=$(jq -er '.Labels["io.finite.profile"]' .bluebuild/iso/source.json)
case "$channel:$profile" in
bluefin-generic:bluefin-generic|latest:bluefin-generic|next:bluefin-next|bluefin-dx-generic:bluefin-dx-generic|dev-next:bluefin-dx-next) ;;
*) echo 'Image profile does not match the requested channel' >&2; exit 1 ;;
esac
bash "$(dirname "${BASH_SOURCE[0]}")/prepare-installer.sh"
skopeo copy --all --preserve-digests "docker://$source" "docker://$repository:$tag"
[[ $(skopeo inspect --format '{{.Digest}}' "docker://$repository:$tag") == "$digest" ]]
cosign verify --key cosign.pub "$repository:$tag" >/dev/null
jq -n --arg image "$source" --arg tag "$repository:$tag" \
  --arg channel "$repository:$channel" --arg profile "$profile" \
  --slurpfile installer .bluebuild/iso/installer.json \
  '{image: $image, installationTag: $tag, updateChannel: $channel, profile: $profile,
    installer: $installer[0]}' \
  >.bluebuild/iso/installation.json
# v0.9.37 constructs IMAGE_TAG from a tag; a digest-only reference becomes latest.
sudo bluebuild generate-iso --run-driver docker --variant kinoite --output-dir .bluebuild/iso \
  --iso-name "finite-$profile.iso" image "$repository:$tag"
# Confirm that the install source tag has not changed while the ISO was assembled.
[[ $(skopeo inspect --format '{{.Digest}}' "docker://$repository:$tag") == "$digest" ]]
(cd .bluebuild/iso && sha256sum -- *.iso installation.json >SHA256SUMS)
