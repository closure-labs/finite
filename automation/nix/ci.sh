#!/usr/bin/env bash
set -euo pipefail

repo_root="${PURPLEFIN_SOURCE_ROOT:-$PWD}"
[[ -f "${repo_root}/flake.nix" ]] || {
  echo "Run this command from the Purplefin repository root" >&2
  exit 2
}

nix --accept-flake-config flake check \
  "git+file://${repo_root}" \
  --print-build-logs \
  "$@"

mapfile -t check_names < <(jq -er '.names[]' <<<"${PURPLEFIN_CHECKS:?}")
mapfile -t check_paths < <(jq -er '.paths[]' <<<"${PURPLEFIN_CHECKS}")
[[ "${#check_names[@]}" == "${#check_paths[@]}" ]]
nix --accept-flake-config build --no-link "${check_paths[@]}"
max_closure_size=$((1024 * 1024))
for index in "${!check_paths[@]}"; do
  name="${check_names[$index]}"
  path="${check_paths[$index]}"
  [[ -e "${path}" ]] || {
    echo "The completed Flake check did not realize ${name}: ${path}" >&2
    exit 1
  }
  closure_size="$({
    nix path-info --json --json-format 1 --closure-size "${path}" |
      jq -er 'to_entries[0].value.closureSize'
  })"
  if ((closure_size > max_closure_size)); then
    printf '%s proof closure is %s bytes; cache limit is %s bytes\n' \
      "${name}" "${closure_size}" "${max_closure_size}" >&2
    exit 1
  fi
  printf '%s\t%s bytes\t%s\n' "${name}" "${closure_size}" "${path}"
done

if [[ "${PURPLEFIN_CACHE_PUSH:-true}" == true && -n "${CACHIX_AUTH_TOKEN:-}" ]]; then
  for path in "${check_paths[@]}"; do
    cachix push --omit-deriver purplefin "${path}"
  done
elif [[ "${PURPLEFIN_CACHE_PUSH:-true}" == true ]]; then
  echo "CACHIX_AUTH_TOKEN is unavailable; proof outputs were not pushed" >&2
fi
