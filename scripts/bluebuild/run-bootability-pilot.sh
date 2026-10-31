#!/usr/bin/env bash
# Hosted diagnostic only; no production qualification/promotion entry point.
set -euo pipefail
python3 scripts/bluebuild/bootability-pilot.py preflight
[[ $PROFILE =~ ^finite(-dev)?$ ]]
[[ $CANDIDATE_DIGEST =~ ^sha256:[0-9a-f]{64}$ && $PREVIOUS_DIGEST =~ ^sha256:[0-9a-f]{64}$ ]]
[[ $CANDIDATE_DIGEST != "$PREVIOUS_DIGEST" ]]
candidate="ghcr.io/closure-labs/finite@$CANDIDATE_DIGEST"
cosign verify --new-bundle-format=false --key cosign.pub "$candidate" >/dev/null
mkdir -p .bluebuild
skopeo inspect "docker://$candidate" >.bluebuild/pilot-image.json
jq -e --arg profile "$PROFILE" --arg revision "$SOURCE_REVISION" --arg identity "$BUILD_IDENTITY" \
  '.Labels["io.finite.profile"] == $profile and .Labels["org.opencontainers.image.revision"] == $revision and .Labels["io.finite.build-inputs"] == $identity' \
  .bluebuild/pilot-image.json >/dev/null
# Read the expected kernel from signed immutable image bytes, never the guest.
docker pull "$candidate" >/dev/null
container=$(docker create "$candidate" /bin/true)
trap 'docker rm "$container" >/dev/null 2>&1 || true' EXIT
docker cp "$container:/usr/share/finite/profile.json" .bluebuild/pilot-profile.json
jq -n --arg profile "$PROFILE" --arg identity "$BUILD_IDENTITY" --arg revision "$SOURCE_REVISION" \
  --slurpfile image .bluebuild/pilot-profile.json \
  '{profile:$profile,kernel:$image[0].kernelRelease,identity:$identity,revision:$revision}' >.bluebuild/pilot-candidate.json
docker rm "$container" >/dev/null
trap - EXIT
# Use exactly the existing encrypted installer, fstab hook, firmware and bootloader.
FINITE_PREDECESSOR_DIGEST="$PREVIOUS_DIGEST" ISO_OUTPUT_DIR=.bluebuild/pilot-iso \
  bash scripts/bluebuild/iso.sh "$PROFILE" "$PREVIOUS_DIGEST"
FINITE_BOOTABILITY_PILOT=true FINITE_SECURE_BOOT=true \
  bash scripts/bluebuild/vm-acceptance.sh .bluebuild/pilot-iso "$candidate" upgrade
python3 scripts/bluebuild/bootability-pilot.py validate .bluebuild/bootability-pilot/receipt.json
