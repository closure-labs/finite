#!/usr/bin/env bash
set -euo pipefail
test -n "${COSIGN_PRIVATE_KEY:?}"
root="$PWD"
cd .bluebuild/release
mapfile -t isos < <(find . -maxdepth 1 -type f -name '*.iso')
[[ ${#isos[@]} == 1 ]]
if (( $(stat -c %s "${isos[0]}") > 1992294400 )); then
  split --bytes=1900M --numeric-suffixes=0 --suffix-length=3 "${isos[0]}" "${isos[0]}.part-"
  rm -- "${isos[0]}"
fi
rm -f SHA256SUMS SHA256SUMS.bundle.json
mapfile -d '' -t assets < <(find . -maxdepth 1 -type f -print0 | LC_ALL=C sort -z)
sha256sum -- "${assets[@]}" >SHA256SUMS
cosign sign-blob --yes --key env://COSIGN_PRIVATE_KEY --bundle SHA256SUMS.bundle.json SHA256SUMS
cosign verify-blob --key "$root/cosign.pub" --bundle SHA256SUMS.bundle.json SHA256SUMS
