#!/usr/bin/env bash
# Run interactively on this workstation. Passwords stay in local prompts.
set -euo pipefail
[[ -t 0 ]] || { echo 'Run this script in a local terminal.' >&2; exit 1; }
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
inventory="$root/artifacts/workstation-recovery/inventory.json"
[[ -f $inventory ]]
work="$root/artifacts/workstation-recovery/runs/$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$work"
for tool in age gpg gpgconf pass cryptsetup efibootmgr lsblk sfdisk tar python3; do
  command -v "$tool" >/dev/null
done
# Capture only the workstation layout already inspected for this migration.
[[ $(lsblk -dnro PARTUUID /dev/nvme0n1p1) == 5bc0db94-2336-4824-b55c-1c6d8395221b ]]
[[ $(lsblk -dnro UUID /dev/nvme0n1p8) == c9dbefef-23cd-4ca8-86f2-8332f16e8bd4 ]]
recovery_parent="$HOME/.local/state/finite-recovery"
install -d -m 0700 "$recovery_parent"
recovery="$recovery_parent/$(date -u +%Y%m%dT%H%M%SZ)"
sudo bash "$root/scripts/workstation/capture-recovery.sh" /dev/nvme0n1 /dev/nvme0n1p8 "$recovery"
sudo chown -R --no-dereference "$(id -u):$(id -g)" "$recovery"
# Add just this small recovery capture, never the earlier full trial bundle.
python3 - "$inventory" "$work/inventory.json" "$recovery" <<'PY'
import json,sys
from pathlib import Path
plan=json.loads(Path(sys.argv[1]).read_text())
recovery=Path(sys.argv[3]).resolve()
assert not any(recovery.is_relative_to(Path(p)) for p in plan['exclude']), 'Recovery capture is excluded'
plan['include'].append(str(recovery))
Path(sys.argv[2]).write_text(json.dumps(plan,indent=2)+'\n')
PY
python3 "$root/scripts/workstation/recovery-backup.py" create --inventory "$work/inventory.json" --work "$work"
args=()
if [[ $# -gt 0 ]]; then args+=(--pass-entry "$1"); fi
python3 "$root/scripts/workstation/recovery-backup.py" verify --work "$work" "${args[@]}"
