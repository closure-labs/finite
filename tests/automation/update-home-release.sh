#!/usr/bin/env bash
set -euo pipefail

test_root="$(mktemp -d)"
trap 'rm -rf "${test_root}"' EXIT

fixture_files=(
	flake.nix
	flake.lock
	lib/ci-applications/validate-locks.nix
	docs/ci-and-releases.md
	docs/configuration.md
	docs/installation.md
)

make_fixture() {
	local fixture=$1 file
	mkdir -p "${fixture}"
	for file in "${fixture_files[@]}"; do
		mkdir -p "${fixture}/$(dirname "${file}")"
		cp "${file}" "${fixture}/${file}"
	done
}

git() {
	if [[ "$*" == *NixOS/nixpkgs.git* ]]; then
		[[ "${UPSTREAM_ERROR:-false}" != true ]] || return 128
		[[ "${NIXPKGS_UPSTREAM_AVAILABLE}" == true ]] || return 2
	else
		[[ "${HOME_MANAGER_UPSTREAM_AVAILABLE}" == true ]] || return 2
	fi
}

python3() {
	if [[ "$*" == *nixpkgs-26.11-chilled* ]]; then
		[[ "${MIRROR_ERROR:-false}" != true ]] || return 1
		[[ "${NIXPKGS_MIRROR_AVAILABLE}" == true ]] || return 3
	else
		[[ "${HOME_MANAGER_MIRROR_AVAILABLE}" == true ]] || return 3
	fi
}

nix() {
	{
		printf 'nix'
		printf ' %q' "$@"
		printf '\n'
	} >>"${MOCK_LOG}"
}

timeout() { shift; "$@"; }
export -f python3 git nix timeout
export NIXPKGS_UPSTREAM_AVAILABLE=true
export HOME_MANAGER_UPSTREAM_AVAILABLE=true
export NIXPKGS_MIRROR_AVAILABLE=true
export HOME_MANAGER_MIRROR_AVAILABLE=true

available_fixture="${test_root}/available"
make_fixture "${available_fixture}"
export MOCK_LOG="${test_root}/available.log"
output_file="${test_root}/available.output"
FINITE_SOURCE_ROOT="${available_fixture}" finite-update-home-release "${output_file}"
grep -qFx 'changed=true' "${output_file}"
grep -qFx 'release=26.11' "${output_file}"
grep -qF 'nixpkgs-26.11-chilled/0.1' "${available_fixture}/flake.nix"
grep -qF 'home-manager/0.2611' "${available_fixture}/flake.nix"
grep -qF 'nix --accept-flake-config flake update nixpkgs home-manager' "${MOCK_LOG}"

unavailable_fixture="${test_root}/unavailable"
make_fixture "${unavailable_fixture}"
export MOCK_LOG="${test_root}/unavailable.log"
export HOME_MANAGER_UPSTREAM_AVAILABLE=false
output_file="${test_root}/unavailable.output"
before="$(sha256sum "${unavailable_fixture}/flake.nix")"
FINITE_SOURCE_ROOT="${unavailable_fixture}" finite-update-home-release "${output_file}"
after="$(sha256sum "${unavailable_fixture}/flake.nix")"
grep -qFx 'changed=false' "${output_file}"
grep -qFx 'release=26.05' "${output_file}"
[[ "${before}" == "${after}" ]]
test ! -e "${MOCK_LOG}"

export HOME_MANAGER_UPSTREAM_AVAILABLE=true
for scenario in missing-mirror upstream-error mirror-error; do
  fixture="${test_root}/${scenario}"
  make_fixture "$fixture"
  export MOCK_LOG="${fixture}/calls"
  output_file="${fixture}/output"
  before=$(sha256sum "${fixture}/flake.nix")
  export UPSTREAM_ERROR=false MIRROR_ERROR=false NIXPKGS_MIRROR_AVAILABLE=true
  case "$scenario" in
    missing-mirror) export NIXPKGS_MIRROR_AVAILABLE=false ;;
    upstream-error) export UPSTREAM_ERROR=true ;;
    mirror-error) export MIRROR_ERROR=true ;;
  esac
  if FINITE_SOURCE_ROOT="$fixture" finite-update-home-release "$output_file"; then
    [[ "$scenario" == missing-mirror ]]
    grep -qFx 'changed=false' "$output_file"
  else
    [[ "$scenario" != missing-mirror ]]
    [[ ! -e "$output_file" ]]
  fi
  [[ "$(sha256sum "${fixture}/flake.nix")" == "$before" ]]
  [[ ! -e "$MOCK_LOG" ]]
done
