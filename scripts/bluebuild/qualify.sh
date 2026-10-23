#!/usr/bin/env bash
set -euo pipefail
phase="${1:-all}"
[[ $phase =~ ^(all|fresh|upgrade)$ ]]
candidate="ghcr.io/closure-labs/finite@${CANDIDATE_DIGEST:?}"
[[ $CANDIDATE_DIGEST =~ ^sha256:[0-9a-f]{64}$ ]]
[[ ${BUILD_IDENTITY:?} =~ ^v1:[0-9a-f]{64}$ ]]
[[ ${PROFILE:?} =~ ^finite(-dev)?$ ]]
[[ ${SOURCE_REVISION:?} =~ ^[0-9a-f]{40}$ ]]
iso_preservation_enabled=$(python3 scripts/ci/ci-options.py --iso-preservation "$PROFILE")
mkdir -p .bluebuild
rm -f ".bluebuild/$PROFILE-acceptance.json"
python3 scripts/bluebuild/qualification-preflight.py --revision "$GITHUB_SHA"
cosign verify --new-bundle-format=false --key cosign.pub "$candidate" >/dev/null
skopeo inspect "docker://$candidate" | jq -e --arg identity "$BUILD_IDENTITY" \
  --arg profile "$PROFILE" --arg revision "$SOURCE_REVISION" '
  .Labels["io.finite.build-inputs"] == $identity and
  .Labels["io.finite.profile"] == $profile and
  .Labels["org.opencontainers.image.revision"] == $revision' >/dev/null
run_phase() {
  local current=$1 iso_dir digest target started reused status
  started=$SECONDS
  iso_dir=.bluebuild/iso-candidate
  digest=$CANDIDATE_DIGEST
  target=''
  if [[ $current == upgrade ]]; then
    [[ ${PREVIOUS_DIGEST:-} =~ ^sha256:[0-9a-f]{64}$ ]]
    iso_dir=.bluebuild/iso-predecessor
    digest=$PREVIOUS_DIGEST
    target=$candidate
  fi
  python3 scripts/bluebuild/qualification-context.py context --phase "$current"
  python3 scripts/bluebuild/qualification-preflight.py --revision "$GITHUB_SHA"
  reused=false
  if [[ ${FINITE_VALIDATION_ONLY:-false} != true && $current == upgrade && $iso_preservation_enabled == true ]]; then
    status=0
    python3 scripts/bluebuild/measure.py predecessor-iso-reuse \
      nix develop --file lib/ci-tools.nix shell --command python3 scripts/bluebuild/reuse-predecessor-iso.py --profile "$PROFILE" --digest "$digest" --output "$iso_dir" || status=$?
    if [[ $status == 0 ]]; then reused=true; fi
    if [[ $status != 0 && $status != 3 ]]; then return "$status"; fi
  fi
  if [[ $reused != true ]]; then
    if [[ $current == upgrade ]]; then
      FINITE_PREDECESSOR_DIGEST="$PREVIOUS_DIGEST" ISO_OUTPUT_DIR="$iso_dir" \
        bash scripts/bluebuild/iso.sh "$CHANNEL" "$digest"
    else
      ISO_OUTPUT_DIR="$iso_dir" bash scripts/bluebuild/iso.sh "$CHANNEL" "$digest"
    fi
  fi
  # VM preparation personalizes a copy in /tmp; retain these pristine bytes.
  FINITE_SECURE_BOOT=true python3 scripts/bluebuild/measure.py vm-acceptance bash scripts/bluebuild/vm-acceptance.sh "$iso_dir" "$target" "$current"
  python3 scripts/bluebuild/qualification-context.py bind-phase --phase "$current"
  printf 'Qualification %s completed in %s seconds\n' "$current" "$((SECONDS - started))"
}
if [[ $phase == all || $phase == fresh ]]; then run_phase fresh; fi
if [[ $phase == upgrade || ($phase == all && -n ${PREVIOUS_DIGEST:-}) ]]; then run_phase upgrade; fi
if [[ $phase == all ]]; then python3 scripts/bluebuild/qualification-context.py aggregate; fi
