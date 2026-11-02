#!/usr/bin/env bash
# Build a disposable installer from the exact local PR image, with no registry push.
set -euo pipefail
profile=${1:?profile required}
[[ $profile =~ ^finite(-dev)?$ ]]
export PROFILE="$profile"
unset CANDIDATE_DIGEST
[[ ${GITHUB_ACTIONS:-} == true && ${GITHUB_REPOSITORY:-} == closure-labs/finite ]]
[[ ${GITHUB_EVENT_NAME:-} == pull_request || ${GITHUB_EVENT_NAME:-} == merge_group ]]
[[ ${GITHUB_REF:-} != refs/heads/main ]]
[[ ${GITHUB_SHA:-} =~ ^[0-9a-f]{40}$ ]]
work=$(mktemp -d /tmp/finite-local-vm.XXXXXXXX)
trap 'rm -rf -- "$work"' EXIT
# inspect-built.sh records Docker's display ID, which is commonly abbreviated.
# Resolve it through the local daemon before enforcing an immutable full ID.
reference=$(cat ".bluebuild/$profile-image-ref.txt")
image=$(docker inspect --format '{{.Id}}' "$reference")
[[ $image =~ ^sha256:[0-9a-f]{64}$ ]] || {
  echo 'Local VM validation could not resolve the assembled image to a full Docker ID.' >&2
  exit 1
}
tag="v${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}"
[[ $tag =~ ^v[0-9]+-[0-9]+$ ]]
local_ref="localhost/finite-validation:$tag"
docker tag "$image" "$local_ref"
# OCI format makes the manifest embedded by the installer stable across copies.
python3 scripts/bluebuild/measure.py local-vm-oci-export \
  skopeo copy --format oci "docker-daemon:$local_ref" "oci-archive:$work/candidate.tar:$tag"
skopeo inspect --raw "oci-archive:$work/candidate.tar:$tag" >"$work/source-manifest.json"
digest="sha256:$(sha256sum "$work/source-manifest.json" | cut -d' ' -f1)"
export CANDIDATE_DIGEST="$digest"
version=$(docker run --rm --entrypoint /bin/sh "$image" -c '. /usr/lib/os-release; printf "%s" "$VERSION_ID"')
[[ $version =~ ^[0-9]{1,3}$ ]]
export ISO_OUTPUT_DIR="$work/iso"
python3 scripts/bluebuild/measure.py local-vm-installer-prepare \
  bash scripts/bluebuild/prepare-installer.sh
installer=$(jq -er .cliAlias sources/bluebuild-installer.json)
# This is the pinned installer's native local-archive mode, also used by the
# locked BlueBuild CLI. Only the disposable install reference is unsigned.
# Secure Boot and enforcing SELinux remain exercised by vm-acceptance.sh.
python3 scripts/bluebuild/measure.py local-vm-iso-build sudo docker run --rm --privileged \
  -v "$work:/img_src:ro" -v "$ISO_OUTPUT_DIR:/build-container-installer/build" \
  "$installer" "IMAGE_SRC=oci-archive:/img_src/candidate.tar:$tag" \
  IMAGE_REPO=localhost IMAGE_NAME=finite-validation "IMAGE_TAG=$tag" IMAGE_SIGNED=false \
  "VERSION=$version" VARIANT=Kinoite "ISO_NAME=build/$profile.iso" \
  SECURE_BOOT_KEY_URL=pinned ENROLLMENT_PASSWORD=universalblue
jq -n --arg image "local-image@$digest" --arg tag "$local_ref" \
  --arg channel "ghcr.io/closure-labs/finite:$profile" --arg profile "$profile" \
  --arg revision "$GITHUB_SHA" --slurpfile installer "$ISO_OUTPUT_DIR/installer.json" \
  '{localValidation:true,sourceRevision:$revision,image:$image,installationTag:$tag,
    updateChannel:$channel,profile:$profile,installer:$installer[0]}' >"$ISO_OUTPUT_DIR/installation.json"
cp "$work/source-manifest.json" "$ISO_OUTPUT_DIR/source-manifest.json"
(cd "$ISO_OUTPUT_DIR" && sha256sum -- *.iso installation.json source-manifest.json >SHA256SUMS)
FINITE_LOCAL_VM_VALIDATION=true FINITE_SECURE_BOOT=true \
  python3 scripts/bluebuild/measure.py local-vm-acceptance \
    bash scripts/bluebuild/vm-acceptance.sh "$ISO_OUTPUT_DIR" '' fresh
mv .bluebuild/vm-local .bluebuild/vm-local-fresh
if [[ $profile == finite && $(python3 scripts/ci/native-nix-selection.py) == true ]]; then
  # Reuse this exact candidate ISO; change only the installed persistent Nix
  # fixture. The predecessor is read by immutable digest and authenticated
  # with the existing public key; no registry alias or signing policy changes.
  predecessor=$(skopeo inspect --format '{{.Digest}}' docker://ghcr.io/closure-labs/finite:finite)
  [[ $predecessor =~ ^sha256:[0-9a-f]{64}$ ]]
  reference="ghcr.io/closure-labs/finite@$predecessor"
  cosign verify --new-bundle-format=false --key cosign.pub "$reference" >"$work/predecessor-signature.json"
  docker pull "$reference"
  container=$(docker create --network=none "$reference")
  mkdir -p "$work/predecessor-media"
  # Keep Docker's archive ownership metadata; extracting on the runner first
  # would replace root ownership with the runner's UID.
  if ! docker cp "$container:/usr/lib/finite/determinate-nix-seed" - >"$work/predecessor-media/state.tar"; then
    docker rm "$container"; exit 1
  fi
  docker rm "$container"
  [[ $(stat -c '%s' "$work/predecessor-media/state.tar") -le 1073741824 ]]
  python3 - "$work/predecessor-media/state.tar" <<'SEED_ARCHIVE'
import sys, tarfile
from pathlib import PurePosixPath
with tarfile.open(sys.argv[1]) as archive:
    members = archive.getmembers()
    assert 0 < len(members) <= 200000
    names = {member.name.rstrip('/') for member in members}
    assert 'determinate-nix-seed/receipt.json' in names
    assert 'determinate-nix-seed/store' in names
    assert 'determinate-nix-seed/var/nix/db' in names
    assert all(PurePosixPath(member.name).parts[0] == 'determinate-nix-seed'
               and '..' not in PurePosixPath(member.name).parts and not member.isdev()
               for member in members)
SEED_ARCHIVE
  jq -n --arg image "$reference" --arg digest "$predecessor" --arg revision "$GITHUB_SHA" \
    --arg archive "$(sha256sum "$work/predecessor-media/state.tar" | cut -d' ' -f1)" \
    '{schema:1,image:$image,imageDigest:$digest,candidateSource:$revision,archiveSha256:$archive}' \
    >"$work/predecessor-media/provenance.json"
  cp "$work/predecessor-media/provenance.json" ".bluebuild/$profile-native-predecessor.json"
  FINITE_LOCAL_VM_VALIDATION=true FINITE_SECURE_BOOT=true \
    FINITE_NATIVE_NIX_PREDECESSOR="$work/predecessor-media" \
    python3 scripts/bluebuild/measure.py local-vm-persistent-nix \
      bash scripts/bluebuild/vm-acceptance.sh "$ISO_OUTPUT_DIR" '' fresh
  mv .bluebuild/vm-local .bluebuild/vm-local-persistent-nix
fi
