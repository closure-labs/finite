#!/usr/bin/env bash
# Run image parsing in a separate, memory-limited service on hosted Linux CI.
set -euo pipefail
image="${1:?immutable image required}"
directory="${2:?evidence directory required}"
[[ $image =~ ^ghcr\.io/closure-labs/finite@sha256:[0-9a-f]{64}$ ]]
[[ ${GITHUB_ACTIONS:-} == true ]] || {
  echo 'Image scanning is hosted-only; use the GitHub image-security workflow.' >&2
  exit 2
}
[[ ! -e $directory && ! -L $directory ]] || {
  echo 'Security evidence directory already exists; refusing stale results.' >&2
  exit 2
}
# Reserve 4 GiB of currently available RAM for the runner and other services.
# Public standard runners can support a 10 GiB cap; smaller hosts remain bounded.
# The Go limit alone is soft and cannot protect the host.
available_kib=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
[[ $available_kib =~ ^[0-9]+$ ]] || { echo "Cannot measure available memory" >&2; exit 2; }
limit_mib=$((available_kib / 1024 - 4096))
((limit_mib > 10240)) && limit_mib=10240
((limit_mib >= 1024)) || { echo "Insufficient available memory for a bounded scanner" >&2; exit 2; }
go_limit_mib=$((limit_mib * 4 / 5))
scanner_python=$(command -v python3)
unit="finite-image-security-$BASHPID-$RANDOM"
# shellcheck disable=SC2329 # Invoked by EXIT, including INT/TERM exit traps.
cleanup() {
  sudo systemctl stop "$unit.service" >/dev/null 2>&1 || true
  sudo systemctl reset-failed "$unit.service" >/dev/null 2>&1 || true
}
trap 'cleanup' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -p "$(dirname "$directory")"
log="$(realpath -m "$directory").runner.log"
{
  echo "Scanner memory limit: $limit_mib MiB; reserved headroom: 4096 MiB; swap: 0; Go soft limit: $go_limit_mib MiB; catalog workers: 1"
  head -3 /proc/meminfo
} >"$log"
set +e
sudo systemd-run --unit="$unit" --wait --pipe --service-type=exec \
  --property="MemoryMax=${limit_mib}M" --property=MemorySwapMax=0 --property=OOMPolicy=stop \
  --property=NoNewPrivileges=yes --property=CapabilityBoundingSet= --property=ProtectControlGroups=yes \
  --property="User=$(id -u)" --property="Group=$(id -g)" \
  --working-directory="$PWD" \
  --setenv="PATH=$PATH" --setenv="HOME=$HOME" \
  --setenv="GITHUB_SHA=${GITHUB_SHA:-}" --setenv="GITHUB_REPOSITORY=${GITHUB_REPOSITORY:-}" \
  --setenv="GITHUB_ACTIONS=${GITHUB_ACTIONS:-}" \
  --setenv="GOMEMLIMIT=${go_limit_mib}MiB" --setenv=SYFT_PARALLELISM=1 --setenv=SYFT_LOG_LEVEL=info \
  "$scanner_python" "$(dirname "${BASH_SOURCE[0]}")/security-scan.py" "$@" 2>&1 | tee -a "$log"
status=${PIPESTATUS[0]}
set -e
sudo systemctl show "$unit.service" --property=Result --property=ExecMainStatus \
  --property=MemoryPeak --property=MemoryMax --property=MemorySwapMax 2>&1 | tee -a "$log" >/dev/null || true
mkdir -p "$directory"
cp "$log" "$directory/runner-resources.log"
rm -f "$log"
# A killed parser cannot write its own failure record. systemd can also treat
# some signal exits as clean, so its exit status alone never grants signing.
status=$("$scanner_python" - "$directory/security-result.json" "$image" "$status" <<'PYRESULT'
import json
from pathlib import Path
import sys
path = Path(sys.argv[1])
status = int(sys.argv[3])
error = 'Bounded scanner service failed; see runner-resources.log'
try:
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Security result exceeds the evidence size limit')
    result = json.loads(path.read_text())
    if status == 0 and (result.get('status') != 'pass' or result.get('image') != sys.argv[2]):
        raise ValueError('Scanner service exited without a matching passing security result')
    if status != 0 and result.get('status') not in ('blocked', 'scanner-error'):
        raise ValueError('Failed scanner service returned inconsistent evidence')
except (OSError, ValueError, AttributeError) as failure:
    if status == 0:
        status = 2
    path.write_text(json.dumps({'schema': 1, 'status': 'scanner-error', 'image': sys.argv[2],
                               'error': error + ': ' + str(failure), 'exitCode': status}, indent=2) + '\n')
print(status)
PYRESULT
)
exit "$status"
