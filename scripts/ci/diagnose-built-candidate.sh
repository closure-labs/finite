#!/usr/bin/env bash
# Opt-in diagnostic for one already verified local validation image.
set -euo pipefail
profile="${1:?profile required}"
case "$profile" in
  finite|finite-dev) ;;
  *) echo 'Unsupported diagnostic profile' >&2; exit 2 ;;
esac
[[ ${GITHUB_ACTIONS:-} == true && ${GITHUB_REPOSITORY:-} == closure-labs/finite &&
   -n ${GITHUB_REF:-} && ${GITHUB_REF} != refs/heads/main ]] || {
  echo 'Built-image diagnostics require a hosted non-main Finite validation job' >&2
  exit 2
}
[[ ${GITHUB_SHA:-} =~ ^[0-9a-f]{40}$ && ${RUNNER_TEMP:-} == /* && -d $RUNNER_TEMP && ! -L $RUNNER_TEMP ]]
script_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
scanner_python=$(command -v python3)
directory="$PWD/.bluebuild/diagnostic-$profile"
[[ ! -e $directory && ! -L $directory ]] || { echo 'Refusing existing diagnostic evidence' >&2; exit 2; }
mkdir -p "$(dirname "$directory")"
temporary=$(mktemp -d "$RUNNER_TEMP/finite-built-diagnostic.XXXXXX")
unit="finite-built-diagnostic-$BASHPID-$RANDOM"
log="$directory.runner.log"
image=local-oci-unvalidated
native_verdict_complete=false
# shellcheck disable=SC2329 # Used by exit/signal traps.
cleanup() {
  status=$?
  if [[ $status != 0 && $native_verdict_complete != true && $status != 130 && $status != 143 ]]; then status=2; fi
  sudo systemctl stop "$unit.service" >/dev/null 2>&1 || true
  sudo systemctl reset-failed "$unit.service" >/dev/null 2>&1 || true
  rm -rf -- "$temporary"
  if [[ -f $log ]]; then
    mkdir -p "$directory"
    cp "$log" "$directory/runner-resources.log"
    rm -f "$log"
  fi
  if [[ $status != 0 && ! -e $directory/security-result.json ]]; then
    mkdir -p "$directory"
    "$scanner_python" - "$directory/security-result.json" "$image" <<'PYFAIL'
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({'schema': 1, 'status': 'scanner-error', 'image': sys.argv[2],
    'error': 'Built-image diagnostic failed before a native verdict; inspect workflow/runner logs',
    'sourceType': 'locally-built-unpublished', 'signatureVerified': False, 'releaseEligible': False}, indent=2)+'\n')
PYFAIL
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
available_kib=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
[[ $available_kib =~ ^[0-9]+$ ]] || { echo 'Cannot measure available memory' >&2; exit 2; }
limit_mib=$((available_kib / 1024 - 4096))
((limit_mib > 10240)) && limit_mib=10240
((limit_mib >= 1024)) || { echo 'Insufficient available memory for bounded diagnostic' >&2; exit 2; }
go_limit_mib=$((limit_mib * 4 / 5))
printf 'MemoryMax=%s MiB; reserved headroom=4096 MiB; swap=0; runtime=1800s\n' "$limit_mib" >"$log"
inputs=$("$scanner_python" - "$profile" "$GITHUB_SHA" <<'PYINPUT'
import json, re, sys
from pathlib import Path
profile, revision = sys.argv[1:]
def read(path):
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)) or not path.is_file() or path.stat().st_size>1024*1024:
        raise ValueError('Missing bounded regular build evidence')
    return json.loads(path.read_text())
publication=read('.bluebuild/'+profile+'-publication.json')
inspected=read('.bluebuild/'+profile+'-image.json')
receipt=read('.bluebuild/upstream-verified.json')
if type(receipt.get('schema')) is not int or receipt['schema']!=1 or receipt.get('sourceRevision')!=revision or receipt.get('repository')!='closure-labs/finite':
    raise ValueError('Diagnostic requires publisher receipt from this exact verified build')
ref=Path('.bluebuild/'+profile+'-image-ref.txt')
if ref.is_symlink() or not ref.is_file() or ref.stat().st_size>128:
    raise ValueError('Missing bounded verified local image reference')
reference=ref.read_text().strip()
if not isinstance(inspected,list) or len(inspected)!=1:
    raise ValueError('Expected one verified local image')
data=inspected[0]; image=data['Id']; identity=publication['buildIdentity']
if (not re.fullmatch(r'sha256:[0-9a-f]{64}',image) or not re.fullmatch(r'v1:[0-9a-f]{64}',identity)
    or not re.fullmatch(r'(?:sha256:)?[0-9a-f]{12,64}',reference)
    or not image[7:].startswith(reference.removeprefix('sha256:'))
    or publication['profile']!=profile or publication['revision']!=revision
    or publication.get('publish') is not False or data.get('Os')!='linux' or data.get('Architecture')!='amd64'):
    raise ValueError('Diagnostic requires exact unpublished assembled image/build identity')
labels=data['Config']['Labels']
expected={'org.opencontainers.image.revision':revision,'org.opencontainers.image.source':'https://github.com/closure-labs/finite',
          'io.finite.profile':profile,'io.finite.build-inputs':identity,'org.opencontainers.image.base.digest':publication['digest']}
if any(labels.get(k)!=v for k,v in expected.items()):
    raise ValueError('Verified image labels differ from publication record')
print(image);print(identity)
PYINPUT
)
mapfile -t input_values <<<"$inputs"
[[ ${#input_values[@]} == 2 ]]
docker_id=${input_values[0]}
identity=${input_values[1]}
docker image inspect "$docker_id" >"$temporary/docker-inspect.json"
"$scanner_python" - "$temporary/docker-inspect.json" ".bluebuild/$profile-image.json" <<'PYDOCKER'
import json, sys
current, expected=[json.load(open(p)) for p in sys.argv[1:]]
fields=('Id','Os','Architecture','Created','Config','RootFS')
if len(current)!=1 or len(expected)!=1 or any(current[0].get(k)!=expected[0].get(k) for k in fields):
    raise ValueError('Local Docker image changed after assembled-image verification')
PYDOCKER
# Preserve Docker config bytes. OCI conversion can otherwise reserialize config
# and change its digest; a mismatch is fatal, never a semantic identity fallback.
skopeo --command-timeout 600s copy --format v2s2 --image-parallel-copies 1 \
  "docker-daemon:$docker_id" "oci:$temporary/image:audit"
image=$("$scanner_python" - "$script_root" "$temporary/image" "$temporary" "$docker_id" "$profile" "$identity" "$GITHUB_SHA" <<'PYBIND'
import hashlib, importlib.util, json, sys
from pathlib import Path
root,layout,out=map(Path,sys.argv[1:4]); docker_id,profile,identity,revision=sys.argv[4:]
spec=importlib.util.spec_from_file_location('candidate',root/'scripts/ci/local-candidate-evidence.py')
candidate=importlib.util.module_from_spec(spec);spec.loader.exec_module(candidate)
_,index=candidate.raw_document(layout/'index.json')
descriptors=index.get('manifests')
if (index.get('schemaVersion')!=2 or not isinstance(descriptors,list) or len(descriptors)!=1
    or descriptors[0].get('annotations',{}).get('org.opencontainers.image.ref.name')!='audit'):
    raise ValueError('Export requires one exact audit manifest')
_,raw,manifest=candidate.descriptor_blob(layout,descriptors[0],candidate.policy_module.IMAGE_TYPES,metadata=True)
image='ghcr.io/closure-labs/finite@'+descriptors[0]['digest']
candidate.policy_module.manifest_binding(image,{'parent':raw.decode(),'child':None})
_,config_raw,config=candidate.descriptor_blob(layout,manifest['config'],candidate.CONFIG_TYPES,metadata=True)
if manifest['config']['digest']!=docker_id:
    raise ValueError('Exported configuration digest differs from verified Docker image ID')
labels=config['config']['Labels']
if (config.get('os')!='linux' or config.get('architecture')!='amd64'
    or labels.get('io.finite.profile')!=profile or labels.get('io.finite.build-inputs')!=identity
    or labels.get('org.opencontainers.image.revision')!=revision
    or labels.get('org.opencontainers.image.source')!='https://github.com/closure-labs/finite'):
    raise ValueError('Exported immutable config differs from verified candidate')
(out/'image-config.json').write_bytes(config_raw)
print(image)
PYBIND
)
"$scanner_python" "$script_root/scripts/ci/approved-baseline.py" --image "$image" \
  --image-config "$temporary/image-config.json" --receipt .bluebuild/upstream-verified.json \
  --output "$temporary/approved-baseline.json"
# The native helper hashes every layer exactly once before cataloging. The
# preliminary binding above intentionally reads only cheap manifest/config data.
set +e
sudo systemd-run --unit="$unit" --wait --pipe --service-type=exec \
  --property="MemoryMax=${limit_mib}M" --property=MemorySwapMax=0 --property=OOMPolicy=stop \
  --property=RuntimeMaxSec=1800 --property=NoNewPrivileges=yes --property=CapabilityBoundingSet= \
  --property=ProtectControlGroups=yes --property="User=$(id -u)" --property="Group=$(id -g)" \
  --working-directory="$PWD" --setenv="PATH=$PATH" --setenv="HOME=$HOME" \
  --setenv="TMPDIR=$temporary" \
  --setenv="GITHUB_ACTIONS=$GITHUB_ACTIONS" --setenv="GITHUB_REPOSITORY=$GITHUB_REPOSITORY" \
  --setenv="GITHUB_SHA=$GITHUB_SHA" --setenv="GITHUB_RUN_ID=${GITHUB_RUN_ID:-}" \
  --setenv="GITHUB_RUN_ATTEMPT=${GITHUB_RUN_ATTEMPT:-}" \
  --setenv="GOMEMLIMIT=${go_limit_mib}MiB" --setenv=SYFT_PARALLELISM=1 \
  "$scanner_python" "$script_root/scripts/ci/local-candidate-evidence.py" "$temporary/image" "$directory" \
  --profile "$profile" --identity "$identity" --approved-baseline "$temporary/approved-baseline.json" \
  2>&1 | tee -a "$log"
service_status=${PIPESTATUS[0]}
set -e
sudo systemctl show "$unit.service" --property=Result --property=ExecMainStatus --property=MemoryPeak \
  --property=MemoryMax --property=MemorySwapMax 2>&1 | tee -a "$log" >/dev/null || true
# A successful/killed service without exact diagnostic evidence cannot pass.
status=$("$scanner_python" - "$directory/security-result.json" "$image" "$service_status" <<'PYSTATUS'
import json, sys
from pathlib import Path
path,image,service_status=Path(sys.argv[1]),sys.argv[2],int(sys.argv[3])
try:
    if path.is_symlink() or path.stat().st_size>16*1024*1024:
        raise ValueError('Invalid bounded native diagnostic result')
    result=json.loads(path.read_text())
    expected={'pass':0,'blocked':1,'scanner-error':2}.get(result.get('status'))
    if result.get('status')=='complete':
        expected=0 if result.get('mode')=='maintainer-decision' and result.get('scannerHealth')=='healthy' else None
    if (expected is None or result.get('image')!=image or result.get('releaseEligible') is not False
        or result.get('signatureVerified') is not False or result.get('sourceType')!='locally-built-unpublished'
        or service_status!=expected):
        raise ValueError('Native diagnostic verdict/service/provenance mismatch')
    print(expected)
except (OSError,ValueError,TypeError,AttributeError):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink(): path.unlink()
    path.write_text(json.dumps({'schema':1,'status':'scanner-error','image':image,
        'error':'Bounded diagnostic service returned missing/inconsistent evidence; see runner-resources.log',
        'sourceType':'locally-built-unpublished','signatureVerified':False,'releaseEligible':False},indent=2)+'\n')
    print(2)
PYSTATUS
)
native_verdict_complete=true
exit "$status"
