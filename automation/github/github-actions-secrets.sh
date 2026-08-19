#!/usr/bin/env bash
repo_root="${PURPLEFIN_SOURCE_ROOT:-$PWD}"
[[ -f "${repo_root}/secretspec.toml" ]] || {
  echo "Run this command from the Purplefin repository root" >&2
  exit 2
}
exec secretspec export \
  --file "${repo_root}/secretspec.toml" \
  --format gha \
  --profile github-actions \
  --provider github-actions \
  --reason "Purplefin GitHub Actions secret mapping" \
  --scope github-actions
