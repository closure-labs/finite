#!/usr/bin/env bash
# Disposable native source/ISO validation on the dedicated upstream GitHub branch.
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} == true && ${GITHUB_REPOSITORY:-} == closure-labs/finite ]]
case ${GITHUB_REF:-} in
  refs/heads/qualification/native-iso) lifecycle=false ;;
  refs/heads/qualification/native-lifecycle) lifecycle=true ;;
  *) exit 2 ;;
esac
profile=${1:?native profile required}
[[ $profile == finite-native || $profile == finite-native-dev ]]
[[ ${GITHUB_SHA:?} == "$(git rev-parse HEAD)" ]]
umask 077
output="$PWD/.bluebuild/native-iso/$profile"
evidence=".bluebuild/native-validation/$profile"
[[ ! -e $output && ! -e $evidence ]]
mkdir -p "$evidence"
work=$(mktemp -d "$RUNNER_TEMP/native-iso.XXXXXXXX")
podman_started=false
container=''
release_media_images() {
  sudo podman image rm --ignore "localhost/finite-native-installer:$profile" \
    "ghcr.io/closure-labs/finite:$profile"
}
cleanup() {
  if [[ -f $work/recipe.before ]]; then
    cp -- "$work/recipe.before" "recipes/$profile.yml"
  fi
  if [[ -n $container ]]; then
    docker rm "$container" || true
  fi
  rm -rf -- "$work"
  if [[ $podman_started == true ]]; then
    release_media_images || true
  fi
  if [[ -d $output ]]; then
    # The serial transcript and exact checksums are the retained evidence.
    sudo find "$output" -type f -name '*.iso' -delete || true
  fi
}
trap cleanup EXIT
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
cp files/bootc-runtime/receipt.json "$evidence/runtime.json"
tools=''
fixture=sources/native-lifecycle-fixture.json
context="$work/validation-context"
mkdir -p "$context/loader"
cp scripts/native-installer/{Validation.Containerfile,validation-guest.py,validation-guest.service} "$context/"
# Only the host signer uses the disposable key. Both generations share one
# boot certificate so the upgrade does not depend on a new trust enrollment.
openssl req -new -newkey rsa:3072 -nodes -x509 -sha256 -days 7 -subj "/CN=Finite native qualification/" \
  -keyout "$work/vm.key" -out "$work/vm.pem" 2>"$work/keygen.log"

build_sealed_archive() {
  local archive=$1 seal=$2 certificate=$3
  local -a candidates
  printf 'Building the %s image and serial observation layer for %s\n' "$profile" "$(basename "$archive")"
  nice -n 19 bash scripts/bluebuild/build.sh "$profile" false
  mapfile -t candidates < <(docker image ls --filter "label=io.finite.profile=$profile" --format '{{.ID}}' | sort -u)
  [[ ${#candidates[@]} == 1 ]]
  docker tag "${candidates[0]}" "localhost/finite-validation-root:$profile"
  if [[ -f $work/older-loader.rpm ]]; then
    local loader="$context/loader/systemd-bootx64.efi"
    docker run --rm -i --network none --entrypoint /bin/bash "localhost/finite-validation-root:$profile" \
      -euo pipefail -c 'rpm2cpio - | cpio --quiet -i --to-stdout ./usr/lib/systemd/boot/efi/systemd-bootx64.efi' \
      < "$work/older-loader.rpm" > "$loader"
    printf '%s  %s\n' "$(jq -er .baselineLoader.unsignedSha256 "$fixture")" "$loader" | sha256sum --check
  fi
  docker build --pull=false --file "$context/Validation.Containerfile" \
    --build-arg "NATIVE_ROOT=localhost/finite-validation-root:$profile" \
    --tag "localhost/finite-validation:$profile" "$context"
  # This container is only a filesystem source for docker cp. The bootable
  # image may omit CMD, and the placeholder command is never started.
  container=$(docker create "localhost/finite-validation:$profile" /unused)
  docker cp "$container:/etc/pki/akmods/certs/akmods-ublue.der" "$work/module.der"
  docker rm "$container"
  container=''
  openssl x509 -inform DER -in "$work/module.der" -out "$certificate"
  skopeo copy "docker-daemon:localhost/finite-validation:$profile" "oci-archive:$work/raw.oci.tar"
  docker image rm "localhost/finite-validation:$profile" "localhost/finite-validation-root:$profile"
  docker image rm --force "${candidates[0]}"
  # Release both Docker build caches before allocating the canonical trees.
  docker buildx prune --builder bluebuild --all --force
  docker builder prune --all --force
  df -h -- "$work"
  if [[ -z $tools ]]; then
    tools=$(nice -n 19 nix build "${nix_args[@]}" --file lib/ci-tools.nix native-boot-tools --no-link --print-out-paths)
    importer=$(nice -n 19 nix build "${nix_args[@]}" --file lib/ci-tools.nix native-bootc --no-link --print-out-paths)
    export PATH="$importer/bin:$PATH"
    importer_sha=$(sha256sum "$importer/bin/bootc" | cut -d' ' -f1)
    importer_version=$("$importer/bin/bootc" --version)
    printf 'Runner-built importer: %s, sha256:%s (%s)\n' "$importer_version" "$importer_sha" "$importer"
    [[ $importer_version == "$(jq -er .bootcVersion sources/native-composefs-verifier.json)" ]]
  fi
  nice -n 19 python3 scripts/bluebuild/seal-native.py \
    --source "$work/raw.oci.tar" --output "$archive" --work "$seal" \
    --tools "$tools" --profile "$profile" --revision "$GITHUB_SHA" --epoch "$(date +%s)" \
    --validation-only --validation-key "$work/vm.key" --validation-certificate "$work/vm.pem" \
    --validation-importer-sha256 "$importer_sha"
  rm -- "$work/raw.oci.tar"
}

if [[ $lifecycle == true ]]; then
  # The locked RPM was verified against Fedora's published Fedora 45 key.
  # Match both the complete package and its extracted EFI binary to those bytes.
  loader_url=$(jq -er .baselineLoader.url "$fixture")
  [[ $loader_url == https://dl.fedoraproject.org/pub/fedora/linux/releases/45/Everything/x86_64/os/Packages/s/* ]]
  curl --fail --location --silent --show-error --proto '=https' --proto-redir '=https' --retry 3 --max-time 90 \
    --output "$work/older-loader.rpm" "$loader_url"
  printf '%s  %s\n' "$(jq -er .baselineLoader.rpmSha256 "$fixture")" "$work/older-loader.rpm" | sha256sum --check
  jq -e .baselineLoader "$fixture" > "$evidence/baseline-loader.json"
fi
build_sealed_archive "$work/sealed.oci.tar" "$work/seal" "$work/module.pem"
rm -f -- "$work/older-loader.rpm" "$context/loader/systemd-bootx64.efi"
digest=$(tar -xOf "$work/sealed.oci.tar" index.json | jq -er '.manifests[0].digest')
cp "$work/seal/sealed.json" "$work/vm.pem" "$evidence/"
printf 'Building the %s installer ISO\n' "$profile"
podman_started=true
ISO_OUTPUT_DIR="$output" nice -n 19 bash scripts/native-installer/build-iso.sh ghcr.io/closure-labs/finite "$profile" "$digest" \
  "$work/sealed.oci.tar" "$work/seal/sealed.json"
(cd "$output" && sha256sum --check SHA256SUMS)
# Installation consumes the embedded payload from the verified ISO. Give the
# sparse guest disk the space held by the two assembly-only Podman images.
release_media_images
podman_started=false
df -h -- "$work" "$output"
update_args=()
if [[ $lifecycle == true ]]; then
  mkdir "$work/update"
  cp -- "recipes/$profile.yml" "$work/recipe.before"
  python3 - "$profile" "$evidence" <<'PY'
import json
from pathlib import Path
import re
import runpy
import sys

profile, evidence = sys.argv[1:]
upstream = runpy.run_path('scripts/ci/bluefin-upstream.py')
base = upstream['recipes'](include_native=True)[profile]
fixture = json.loads(Path('sources/native-lifecycle-fixture.json').read_text())[profile]
candidate = upstream['digest'](fixture['digest'])
info = upstream['inspect'](base['base'] + '@' + candidate)
if (candidate == base['digest'] or info['Digest'] != candidate or info['Architecture'] != 'amd64'
        or info['Os'] != 'linux' or info['Labels']['org.opencontainers.image.version'] != fixture['version']
        or info['Labels']['ostree.linux'] != fixture['kernelRelease']):
    raise ValueError('Unexpected upstream lifecycle fixture identity')
authentication = upstream['authenticate'](base['base'], candidate)
(Path(evidence) / 'upgrade-upstream.json').write_text(json.dumps({
    'profile': profile, 'base': base['base'] + '@' + base['digest'], 'update': authentication, **fixture,
}, indent=2) + '\n')
recipe = Path('recipes', profile + '.yml')
revised, count = re.subn(r'^image-version: stable@sha256:[0-9a-f]{64}$',
                         'image-version: latest@' + candidate, recipe.read_text(), flags=re.M)
if count != 1:
    raise ValueError('Expected exactly one pinned stable recipe input')
recipe.write_text(revised)
PY
  nice -n 19 bluebuild validate "recipes/$profile.yml"
  build_sealed_archive "$work/update/update.oci.tar" "$work/update-seal" "$work/update-module.pem"
  mv -- "$work/recipe.before" "recipes/$profile.yml"
  jq -e --arg expected "$(jq -er --arg profile "$profile" '.[$profile].kernelRelease' "$fixture")" \
    '.kernelRelease == $expected' "$work/update-seal/sealed.json" >/dev/null
  cp -- "$work/update-seal/sealed.json" "$work/update/update.json"
  cp -- "$work/update/update.json" "$evidence/update.json"
  update_args=(--update-archive "$work/update/update.oci.tar" --update-module-certificate "$work/update-module.pem"
    --baseline-loader "$(jq -er .baselineLoader.loaderInfo "$fixture")"
    --updated-loader "$(jq -er .updateLoaderInfo "$fixture")")
fi
rm -- "$work/vm.key"
printf 'Booting the %s installer in the capped VM\n' "$profile"
nice -n 19 python3 scripts/native-installer/qualify-iso.py \
  --iso "$output/finite-native-installer-$profile.iso" \
  --seal "$work/seal/sealed.json" --certificate "$work/vm.pem" --module-certificate "$work/module.pem" \
  --state "$work/guest" --evidence "$evidence" "${update_args[@]}"
