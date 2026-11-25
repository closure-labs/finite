#!/usr/bin/env bash
# Disposable native source/ISO validation on the dedicated upstream GitHub branch.
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} == true && ${GITHUB_REPOSITORY:-} == closure-labs/finite ]]
[[ ${GITHUB_REF:-} == refs/heads/qualification/native-iso ]]
profile=${1:?native profile required}
[[ $profile == finite-native || $profile == finite-native-dev ]]
[[ ${GITHUB_SHA:?} == "$(git rev-parse HEAD)" ]]
umask 077
work=$(mktemp -d "$RUNNER_TEMP/native-iso.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
mkdir -p .bluebuild/native-validation
nix_args=(--accept-flake-config --max-jobs 1 --cores 2)
# Retain the verified setup-nix substituters while capping every nested build.
NIX_CONFIG="${NIX_CONFIG:-}"$'\nmax-jobs = 1\ncores = 2'
export NIX_CONFIG
# setup-vm-tools supplies the pinned Python with PyYAML. The sealing tool
# environment contains plain Python and is added only inside seal-native.py.
python3 -c 'import yaml'
printf 'Authenticating and validating the %s recipe\n' "$profile"
python3 scripts/ci/bluefin-upstream.py verify --include-native
nice -n 19 bluebuild validate "recipes/$profile.yml"
printf 'Staging the locked runtime and payload for %s\n' "$profile"
nice -n 19 bash scripts/bluebuild/stage.sh "$profile"
printf 'Building the %s image and serial observation layer\n' "$profile"
nice -n 19 bash scripts/bluebuild/build.sh "$profile" false
mapfile -t candidates < <(docker image ls --filter "label=io.finite.profile=$profile" --format '{{.ID}}' | sort -u)
[[ ${#candidates[@]} == 1 ]]
docker tag "${candidates[0]}" "localhost/finite-validation-root:$profile"
docker build --pull=false --file scripts/native-installer/Validation.Containerfile \
  --build-arg "NATIVE_ROOT=localhost/finite-validation-root:$profile" \
  --tag "localhost/finite-validation:$profile" scripts/native-installer
container=$(docker create "localhost/finite-validation:$profile")
docker cp "$container:/etc/pki/akmods/certs/akmods-ublue.der" "$work/module.der"
docker rm "$container"
openssl x509 -inform DER -in "$work/module.der" -out "$work/module.pem"
skopeo copy "docker-daemon:localhost/finite-validation:$profile" "oci-archive:$work/raw.oci.tar"
docker image rm "localhost/finite-validation:$profile" "localhost/finite-validation-root:$profile"
printf 'Building the pinned importer and sealing the %s archive\n' "$profile"
tools=$(nice -n 19 nix build "${nix_args[@]}" --file lib/ci-tools.nix native-boot-tools --no-link --print-out-paths)
importer=$(nice -n 19 nix build "${nix_args[@]}" --file lib/ci-tools.nix native-bootc --no-link --print-out-paths)
export PATH="$importer/bin:$PATH"
importer_sha=$(sha256sum "$importer/bin/bootc" | cut -d' ' -f1)
importer_version=$("$importer/bin/bootc" --version)
printf 'Runner-built importer: %s, sha256:%s (%s)\n' "$importer_version" "$importer_sha" "$importer"
[[ $importer_version == "$(jq -er .bootcVersion sources/native-composefs-verifier.json)" ]]
# Only public certificates and receipts survive. The key is never copied into
# a container build context or mounted in QEMU.
openssl req -new -newkey rsa:3072 -nodes -x509 -sha256 -days 7 -subj "/CN=Finite native qualification/" \
  -keyout "$work/vm.key" -out "$work/vm.pem" 2>"$work/keygen.log"
nice -n 19 python3 scripts/bluebuild/seal-native.py \
  --source "$work/raw.oci.tar" --output "$work/sealed.oci.tar" --work "$work/seal" \
  --tools "$tools" --profile "$profile" --revision "$GITHUB_SHA" --epoch "$(date +%s)" \
  --validation-only --validation-key "$work/vm.key" --validation-certificate "$work/vm.pem" \
  --validation-importer-sha256 "$importer_sha"
rm -f "$work/vm.key" "$work/raw.oci.tar"
digest=$(tar -xOf "$work/sealed.oci.tar" index.json | jq -er '.manifests[0].digest')
cp "$work/seal/sealed.json" "$work/vm.pem" .bluebuild/native-validation/
printf 'Building the %s installer ISO\n' "$profile"
nice -n 19 bash scripts/native-installer/build-iso.sh ghcr.io/closure-labs/finite "$profile" "$digest" \
  "$work/sealed.oci.tar" "$work/seal/sealed.json"
(cd .bluebuild/native-iso && sha256sum --check SHA256SUMS)
rm "$work/sealed.oci.tar"
printf 'Booting the %s installer in the capped VM\n' "$profile"
nice -n 19 python3 scripts/native-installer/qualify-iso.py \
  --iso ".bluebuild/native-iso/finite-native-installer-$profile.iso" \
  --seal "$work/seal/sealed.json" --certificate "$work/vm.pem" --module-certificate "$work/module.pem" \
  --state "$work/guest" --evidence .bluebuild/native-validation
