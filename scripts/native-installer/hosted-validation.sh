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
fixture=sources/native-lifecycle-fixture.json
install_lifecycle_runtime() {
  local generation=$1
  shift
  local source="$RUNNER_TEMP/native-lifecycle-runtimes/$generation"
  [[ ! -e files/bootc-runtime && -d $source && ! -L $source ]]
  for name in bootc-runtime.rpm source-lock.json receipt.json; do
    [[ -f $source/$name && ! -L $source/$name ]]
  done
  # The stage helper rechecks the source, packaging-input and RPM hashes.
  nice -n 19 python3 scripts/bluebuild/stage-bootc-runtime.py --output "$source" "$@"
  cp -a -- "$source" files/bootc-runtime
}
if [[ $lifecycle == true ]]; then
  cp -- "recipes/$profile.yml" "$work/recipe.before"
  python3 - "$profile" "$evidence" "$fixture" <<'PY'
import json
from pathlib import Path
import re
import runpy
import sys

profile, evidence, fixture_path = sys.argv[1:]
upstream = runpy.run_path('scripts/ci/bluefin-upstream.py')
recipe = upstream['recipes'](include_native=True)[profile]
fixture = json.loads(Path(fixture_path).read_text())
baseline = upstream['digest'](fixture['baseline']['digests'][profile])
generations = {'baseline': baseline, 'update': recipe['digest']}
receipts = {}
for generation, digest in generations.items():
    expected = fixture[generation]
    info = upstream['inspect'](recipe['base'] + '@' + digest)
    labels = info['Labels']
    packages = json.loads(labels['dev.hhd.rechunk.info'])['packages']
    if (info['Digest'] != digest or info['Architecture'] != 'amd64' or info['Os'] != 'linux'
            or labels['org.opencontainers.image.version'] != expected['version']
            or labels['ostree.linux'] != expected['kernelRelease']
            or not {'kmod-zfs', 'kmod-v4l2loopback'} <= set(packages)):
        raise ValueError('Unexpected kernel or module packages in lifecycle ' + generation)
    receipts[generation] = {**upstream['authenticate'](recipe['base'], digest),
                            'version': expected['version'], 'kernelRelease': expected['kernelRelease'],
                            'modules': {name: packages[name] for name in ('kmod-zfs', 'kmod-v4l2loopback')}}
(Path(evidence) / 'upgrade-upstream.json').write_text(json.dumps({'profile': profile, **receipts}, indent=2) + '\n')
path = Path('recipes', profile + '.yml')
revised, count = re.subn(r'^image-version: stable@sha256:[0-9a-f]{64}$',
                         'image-version: stable@' + baseline, path.read_text(), flags=re.M)
if count != 1:
    raise ValueError('Expected exactly one pinned stable recipe input')
path.write_text(revised)
PY
  nice -n 19 bluebuild validate "recipes/$profile.yml"
  [[ -d files/payload/home-manager-template ]]
  cp -- .bluebuild/lifecycle-payload.json "$evidence/shared-payload.json"
  install_lifecycle_runtime 44 --validation-fedora44
else
  printf 'Staging the locked runtime and payload for %s\n' "$profile"
  nice -n 19 bash scripts/bluebuild/stage.sh "$profile"
fi
cp files/bootc-runtime/receipt.json "$evidence/runtime.json"
tools=''
context="$work/validation-context"
mkdir "$context"
cp scripts/native-installer/{Validation.Containerfile,validation-guest.py,validation-guest.service,serial_records.py} "$context/"
# Only the host signer uses the disposable key. Both generations share one
# boot certificate so the upgrade does not depend on a new trust enrollment.
openssl req -new -newkey rsa:3072 -nodes -x509 -sha256 -days 7 -subj "/CN=Finite native qualification/" \
  -keyout "$work/vm.key" -out "$work/vm.pem" 2>"$work/keygen.log"

build_sealed_archive() {
  local archive=$1 seal=$2 certificate=$3 expected_kernel=${4:-}
  local -a candidates
  printf 'Building the %s image and serial observation layer for %s\n' "$profile" "$(basename "$archive")"
  nice -n 19 bash scripts/bluebuild/build.sh "$profile" false
  mapfile -t candidates < <(docker image ls --filter "label=io.finite.profile=$profile" --format '{{.ID}}' | sort -u)
  [[ ${#candidates[@]} == 1 ]]
  docker tag "${candidates[0]}" "localhost/finite-validation-root:$profile"
  if [[ -n $expected_kernel ]]; then
    docker run --rm --network none --entrypoint /bin/bash "localhost/finite-validation-root:$profile" \
      -euo pipefail -c '
        for module in zfs v4l2loopback; do
          signer=$(modinfo -k "$1" -F signer "$module")
          test -n "$signer"
          printf "%s %s: %s\n" "$1" "$module" "$signer"
        done
      ' _ "$expected_kernel"
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
  if [[ -n $expected_kernel ]]; then
    jq -e --arg expected "$expected_kernel" '.kernelRelease == $expected' "$seal/sealed.json" >/dev/null
  fi
  rm -- "$work/raw.oci.tar"
}

baseline_kernel=''
if [[ $lifecycle == true ]]; then
  baseline_kernel=$(jq -er .baseline.kernelRelease "$fixture")
fi
build_sealed_archive "$work/sealed.oci.tar" "$work/seal" "$work/module.pem" "$baseline_kernel"
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
  mv -- "$work/recipe.before" "recipes/$profile.yml"
  mv -- files/bootc-runtime "$work/baseline-runtime"
  install_lifecycle_runtime 45
  cp files/bootc-runtime/receipt.json "$evidence/update-runtime.json"
  build_sealed_archive "$work/update/update.oci.tar" "$work/update-seal" "$work/update-module.pem" \
    "$(jq -er .update.kernelRelease "$fixture")"
  cp -- "$work/update-seal/sealed.json" "$work/update/update.json"
  cp -- "$work/update/update.json" "$evidence/update.json"
  update_args=(--update-archive "$work/update/update.oci.tar" --update-module-certificate "$work/update-module.pem"
    --baseline-loader "$(jq -er .baseline.loaderVersion "$fixture")"
    --updated-loader "$(jq -er .update.loaderVersion "$fixture")")
fi
rm -- "$work/vm.key"
printf 'Booting the %s installer in the capped VM\n' "$profile"
nice -n 19 python3 scripts/native-installer/qualify-iso.py \
  --iso "$output/finite-native-installer-$profile.iso" \
  --seal "$work/seal/sealed.json" --certificate "$work/vm.pem" --module-certificate "$work/module.pem" \
  --state "$work/guest" --evidence "$evidence" "${update_args[@]}"
