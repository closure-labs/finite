#!/usr/bin/env bash
set -euo pipefail
candidate="ghcr.io/closure-labs/finite@${CANDIDATE_DIGEST:?}"
[[ $CANDIDATE_DIGEST =~ ^sha256:[0-9a-f]{64}$ ]]
[[ ${BUILD_IDENTITY:?} =~ ^v1:[0-9a-f]{64}$ ]]
[[ ${PROFILE:?} =~ ^bluefin(-dx)?-(generic|next)$ ]]
rm -f ".bluebuild/$PROFILE-acceptance.json"
cosign verify --key cosign.pub "$candidate" >/dev/null
skopeo inspect "docker://$candidate" | jq -e --arg identity "$BUILD_IDENTITY" \
  --arg profile "$PROFILE" --arg revision "${GITHUB_SHA:?}" '
  .Labels["io.finite.build-inputs"] == $identity and
  .Labels["io.finite.profile"] == $profile and
  .Labels["org.opencontainers.image.revision"] == $revision' >/dev/null
bash scripts/bluebuild/iso.sh "$CHANNEL" "$CANDIDATE_DIGEST"
FINITE_SECURE_BOOT=true bash scripts/bluebuild/vm-acceptance.sh .bluebuild/iso '' fresh
if [[ -n ${PREVIOUS_DIGEST:-} ]]; then
  [[ $PREVIOUS_DIGEST =~ ^sha256:[0-9a-f]{64}$ ]]
  rm -f .bluebuild/iso/*.iso
  bash scripts/bluebuild/iso.sh "$CHANNEL" "$PREVIOUS_DIGEST"
  FINITE_SECURE_BOOT=true bash scripts/bluebuild/vm-acceptance.sh .bluebuild/iso "$candidate" upgrade
fi
jq -n --arg candidate "$candidate" --arg previous "${PREVIOUS_DIGEST:-}" \
  --arg profile "$PROFILE" --arg revision "$GITHUB_SHA" --arg identity "$BUILD_IDENTITY" \
  '{schema:1,candidate:$candidate,previousDigest:$previous,profile:$profile,
    revision:$revision,buildIdentity:$identity,secureBoot:true,accepted:true,
    bootstrap:($previous == "")}' >".bluebuild/$PROFILE-acceptance.json"
