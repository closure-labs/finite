#!/usr/bin/env bash
# Pre-enroll the ISO's public module-signing certificate in an ephemeral VM.
set -euo pipefail
iso="${1:?verified ISO required}"
variables="${2:?OVMF variables template required}"
state="${3:?VM state directory required}"
mkdir -p "$state"
xorriso -osirrox on -indev "$iso" -extract /sb_pubkey.der "$state/sb_pubkey.der"
openssl x509 -inform DER -in "$state/sb_pubkey.der" -out "$state/sb_pubkey.pem"
openssl x509 -in "$state/sb_pubkey.pem" -noout -subject -fingerprint -sha256 \
  >"$state/firmware-certificate.log"
# Keep the template's Microsoft trust databases and Secure Boot settings intact.
# This is the same certificate the installer would queue for interactive MOK
# enrollment, not a replacement for shim's signature checks.
virt-fw-vars --input "$variables" --output "$state/OVMF_VARS.fd" \
  --add-mok 605dab50-e046-4300-abb6-3dd810dd8b23 "$state/sb_pubkey.pem" \
  --output-json "$state/firmware.json"
