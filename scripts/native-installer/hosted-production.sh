#!/usr/bin/env bash
# Seal consumption, ISO assembly and VM qualification use no signing secrets.
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} == true && ${GITHUB_REPOSITORY:-} == closure-labs/finite ]]
[[ ${GITHUB_WORKFLOW_REF:-} == closure-labs/finite/.github/workflows/native-production-validation.yml@refs/heads/main ]]
[[ ${GITHUB_REF:-} == refs/heads/main && $SOURCE_REVISION == "$GITHUB_SHA" && $(git rev-parse HEAD) == "$GITHUB_SHA" ]]
[[ $PROFILE == finite-native || $PROFILE == finite-native-dev ]]
[[ $DIGEST =~ ^sha256:[0-9a-f]{64}$ && $SEAL_ARTIFACT == "image-$PROFILE-$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT" ]]
umask 077
work=$(mktemp -d "$RUNNER_TEMP/native-production.XXXXXXXX")
evidence="$PWD/.bluebuild/native-production-evidence"
output="$PWD/.bluebuild/native-iso"
repository=ghcr.io/closure-labs/finite
container=''
cleanup() {
  if [[ -n $container ]]; then sudo podman rm "$container" || true; fi
  sudo podman image rm --ignore "localhost/finite-native-installer:$PROFILE" "$repository:$PROFILE" || true
  rm -rf -- "$work"
}
trap cleanup EXIT
mkdir -p "$evidence"
tools=$(nix build --max-jobs 1 --cores 2 --file lib/ci-tools.nix native-boot-tools --no-link --print-out-paths)
importer=$(nix build --max-jobs 1 --cores 2 --file lib/ci-tools.nix native-bootc --no-link --print-out-paths)
ocr=$(nix build --max-jobs 1 --cores 2 --file lib/ci-tools.nix native-console-ocr --no-link --print-out-paths)
# Keep the VM tool Python (with PyYAML) in front of the plain signing interpreter.
vm_tools=$(dirname "$(command -v python3)")
export PATH="$vm_tools:$importer/bin:$tools/bin:$ocr/bin:$PATH"
python3 scripts/bluebuild/qualification-preflight.py --revision "$GITHUB_SHA"
gh run download "$GITHUB_RUN_ID" --repo "$GITHUB_REPOSITORY" --name "$SEAL_ARTIFACT" --dir "$work"
printf '%s' "$GH_TOKEN" | skopeo login --authfile "$work/auth.json" --username "$GITHUB_ACTOR" --password-stdin ghcr.io
unset GH_TOKEN
image="$repository@$DIGEST"
skopeo inspect --authfile "$work/auth.json" --no-tags "docker://$image" > "$work/registry-image.json"
skopeo copy --preserve-digests --authfile "$work/auth.json" "docker://$image" "oci-archive:$work/production.oci.tar"
rm -- "$work/auth.json"
[[ $(skopeo inspect --raw "oci-archive:$work/production.oci.tar" | sha256sum | cut -d' ' -f1) == "${DIGEST#sha256:}" ]]
certificate="$PWD/$(jq -er .certificate sources/boot-signing.json)"
python3 scripts/bluebuild/verify-native-oci.py --archive "$work/production.oci.tar" \
  --certificate "$certificate" --certificate-sha256 "$(jq -er .certificateDerSha256 sources/boot-signing.json)" \
  --output "$work/registry-integrity.json" --temporary-root "$work"
python3 scripts/native-installer/production-input.py "$work" "$PROFILE" "$DIGEST" > "$work/production-input.json"
cp -- "$work/production-input.json" "$work/registry-integrity.json" "$work/$PROFILE-native-seal.json" "$evidence/"

bash scripts/native-installer/build-iso.sh "$repository" "$PROFILE" "$DIGEST" --production-candidate "$work"
cp -- "$output/installation.json" "$output/SHA256SUMS" "$evidence/"
container=$(sudo podman create "$repository:$PROFILE" /unused)
sudo podman cp "$container:/etc/pki/akmods/certs/akmods-ublue.der" "$work/module.der"
sudo podman rm "$container"
container=''
openssl x509 -inform DER -in "$work/module.der" -out "$work/module.pem"
sudo podman image rm "localhost/finite-native-installer:$PROFILE" "$repository:$PROFILE"
python3 scripts/native-installer/qualify-production.py --iso "$output/finite-native-installer-$PROFILE.iso" \
  --production-input "$work/production-input.json" --certificate "$certificate" --module-certificate "$work/module.pem" \
  --state "$work/guest" --evidence "$evidence"
