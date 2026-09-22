#!/usr/bin/env bash
# Exercise real ISO extraction and OVMF editing; no VM or host firmware writes.
set -euo pipefail
template="${1:?OVMF variables fixture required}"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/tree" "$work/empty"
openssl req -x509 -newkey rsa:2048 -nodes -subj /CN=Finite-VM-test/ \
  -keyout "$work/private.pem" -out "$work/public.pem" -days 1
openssl x509 -in "$work/public.pem" -outform DER -out "$work/tree/sb_pubkey.der"
xorriso -as mkisofs -R -o "$work/fixture.iso" "$work/tree"
virt-fw-vars --input "$template" --output "$work/template.fd" \
  --enroll-redhat --secure-boot --output-json "$work/before.json"
sha256sum "$work/template.fd" "$work/fixture.iso" >"$work/inputs.sha256"
bash scripts/bluebuild/prepare-vm-firmware.sh "$work/fixture.iso" "$work/template.fd" "$work/vm"
# Read back the binary output, rather than trusting only the tool's JSON output.
virt-fw-vars --input "$work/vm/OVMF_VARS.fd" --output-json "$work/after.json"
python3 - "$work" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
def variables(name):
    return {v['name']: v for v in json.loads((root / name).read_text())['variables']}
before, after = variables('before.json'), variables('after.json')
for name, value in before.items():
    assert after[name] == value, f'Firmware variable changed: {name}'
for name in ('PK', 'KEK', 'db', 'dbx', 'SecureBootEnable'):
    assert name in before, f'Test template lacks {name}'
assert before['SecureBootEnable']['data'] == '01'
certificate = (root / 'tree/sb_pubkey.der').read_bytes()
assert certificate.hex() in after['MokList']['data'], 'ISO certificate was not enrolled'
assert (root / 'vm/sb_pubkey.der').read_bytes() == certificate
assert 'MokNew' not in after, 'Enrollment was queued instead of completed'
assert 'MokSBState' not in after, 'Shim signature validation was disabled'
PY
sha256sum -c "$work/inputs.sha256"
xorriso -as mkisofs -R -o "$work/missing.iso" "$work/empty"
if bash scripts/bluebuild/prepare-vm-firmware.sh "$work/missing.iso" "$work/template.fd" "$work/missing"; then
  echo 'Missing ISO certificate was accepted' >&2
  exit 1
fi
test ! -e "$work/missing/OVMF_VARS.fd"
printf 'not a certificate\n' >"$work/tree/sb_pubkey.der"
xorriso -as mkisofs -R -o "$work/invalid.iso" "$work/tree"
if bash scripts/bluebuild/prepare-vm-firmware.sh "$work/invalid.iso" "$work/template.fd" "$work/invalid"; then
  echo 'Invalid ISO certificate was accepted' >&2
  exit 1
fi
test ! -e "$work/invalid/OVMF_VARS.fd"
