#!/usr/bin/env bash
set -euo pipefail
profile="${1:?profile required}"
foundation="${2:?foundation required}"
hardware="${3:?hardware required}"
channel="${4:?update channel required}"
install -d /usr/share/finite
printf '%s\n' "$profile" >/usr/share/finite/build-profile
kernel_release=$(rpm -q --qf '%{EVR}.%{ARCH}\n' kernel-core)
jq -n --arg profile "$profile" --arg foundation "$foundation" \
  --arg hardware "$hardware" --arg channel "$channel" --arg kernel "$kernel_release" \
  '{schema: 1, profile: $profile, foundation: $foundation, hardware: $hardware,
    channel: $channel, kernelRelease: $kernel}' >/usr/share/finite/profile.json
# An ISO-specific tag is only an installation source. Keep its ongoing channel
# in the image metadata so the installed host can explicitly select updates.
printf '%s/%s:%s\n' "$IMAGE_REGISTRY" "$IMAGE_NAME" "$channel" >/usr/share/finite/update-image
