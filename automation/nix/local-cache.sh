#!/usr/bin/env bash
set -euo pipefail

repo_root="${PURPLEFIN_SOURCE_ROOT:-$PWD}"
[[ -f "${repo_root}/flake.nix" ]] || {
  echo "Run this command from the Purplefin repository root" >&2
  exit 2
}
if [[ -z "${CACHIX_AUTH_TOKEN:-}" ]]; then
  token_file="${HOME}/.other-fun-things/.cachix-purplefin-auth"
  [[ -r "${token_file}" ]] || {
    echo "CACHIX_AUTH_TOKEN is unset and ${token_file} is unreadable" >&2
    exit 2
  }
  CACHIX_AUTH_TOKEN="$(<"${token_file}")"
  export CACHIX_AUTH_TOKEN
fi
cd "${repo_root}"
exec secretspec run \
  --file "${repo_root}/secretspec.toml" \
  --provider local \
  --profile local-cache \
  --reason "Purplefin local Nix cache" \
  --scope cachix \
  -- "${PURPLEFIN_CI:?}" "$@"
