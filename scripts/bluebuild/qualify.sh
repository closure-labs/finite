#!/usr/bin/env bash
set -euo pipefail
candidate="ghcr.io/closure-labs/finite@${CANDIDATE_DIGEST:?}"
[[ $CANDIDATE_DIGEST =~ ^sha256:[0-9a-f]{64}$ ]]
[[ ${BUILD_IDENTITY:?} =~ ^v1:[0-9a-f]{64}$ ]]
[[ ${PROFILE:?} =~ ^bluefin(-dx)?-(generic|next)$ ]]
[[ ${SOURCE_REVISION:?} =~ ^[0-9a-f]{40}$ ]]
rm -f ".bluebuild/$PROFILE-acceptance.json"
cosign verify --new-bundle-format=false --key cosign.pub "$candidate" >/dev/null
skopeo inspect "docker://$candidate" | jq -e --arg identity "$BUILD_IDENTITY" \
  --arg profile "$PROFILE" --arg revision "$SOURCE_REVISION" '
  .Labels["io.finite.build-inputs"] == $identity and
  .Labels["io.finite.profile"] == $profile and
  .Labels["org.opencontainers.image.revision"] == $revision' >/dev/null
bash scripts/bluebuild/iso.sh "$CHANNEL" "$CANDIDATE_DIGEST"
FINITE_SECURE_BOOT=true bash scripts/bluebuild/vm-acceptance.sh .bluebuild/iso '' fresh
jq -e --arg candidate "$candidate" --arg profile "$PROFILE" '
  .accepted == true and .secureBoot == true and .encryptedRoot == true and
  .source == $candidate and .profile == $profile
' .bluebuild/vm-fresh/acceptance.json >/dev/null
if [[ -n ${PREVIOUS_DIGEST:-} ]]; then
  [[ $PREVIOUS_DIGEST =~ ^sha256:[0-9a-f]{64}$ ]]
  rm -f .bluebuild/iso/*.iso
  bash scripts/bluebuild/iso.sh "$CHANNEL" "$PREVIOUS_DIGEST"
  FINITE_SECURE_BOOT=true bash scripts/bluebuild/vm-acceptance.sh .bluebuild/iso "$candidate" upgrade
  jq -e --arg candidate "$candidate" --arg profile "$PROFILE" \
    --arg previous "ghcr.io/closure-labs/finite@$PREVIOUS_DIGEST" '
    .accepted == true and .secureBoot == true and .encryptedRoot == true and
    .source == $previous and .target == $candidate and .profile == $profile
  ' .bluebuild/vm-upgrade/acceptance.json >/dev/null
fi
jq -n --arg candidate "$candidate" --arg previous "${PREVIOUS_DIGEST:-}" \
  --arg profile "$PROFILE" --arg revision "$GITHUB_SHA" --arg sourceRevision "$SOURCE_REVISION" --arg identity "$BUILD_IDENTITY" \
  '{schema:1,candidate:$candidate,previousDigest:$previous,profile:$profile,
    revision:$revision,sourceRevision:$sourceRevision,buildIdentity:$identity,secureBoot:true,encryptedRoot:true,accepted:true,
    bootstrap:($previous == "")}' >".bluebuild/$PROFILE-acceptance.json"
python3 scripts/bluebuild/desktop-qualification.py ".bluebuild/$PROFILE-acceptance.json"
