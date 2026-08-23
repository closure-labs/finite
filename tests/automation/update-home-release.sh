#!/usr/bin/env bash
set -euo pipefail

test_root="$(mktemp -d)"
trap 'rm -rf "${test_root}"' EXIT

fixture_files=(
	flake.nix
	flake.lock
	modules/outputs.nix
	lib/ci-applications/validate-locks.nix
	tests/repository/contracts.sh
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
		[[ "${NIXPKGS_UPSTREAM_AVAILABLE}" == true ]]
	else
		[[ "${HOME_MANAGER_UPSTREAM_AVAILABLE}" == true ]]
	fi
}

curl() {
	if [[ "$*" == *nixpkgs-26.11-chilled* ]]; then
		[[ "${NIXPKGS_MIRROR_AVAILABLE}" == true ]]
	else
		[[ "${HOME_MANAGER_MIRROR_AVAILABLE}" == true ]]
	fi
}

nix() {
	{
		printf 'nix'
		printf ' %q' "$@"
		printf '\n'
	} >>"${MOCK_LOG}"
}

export -f curl git nix
export NIXPKGS_UPSTREAM_AVAILABLE=true
export HOME_MANAGER_UPSTREAM_AVAILABLE=true
export NIXPKGS_MIRROR_AVAILABLE=true
export HOME_MANAGER_MIRROR_AVAILABLE=true

available_fixture="${test_root}/available"
make_fixture "${available_fixture}"
export MOCK_LOG="${test_root}/available.log"
output_file="${test_root}/available.output"
PURPLEFIN_SOURCE_ROOT="${available_fixture}" purplefin-update-home-release "${output_file}"
grep -qFx 'changed=true' "${output_file}"
grep -qFx 'release=26.11' "${output_file}"
grep -qF 'nixpkgs-26.11-chilled/0.1' "${available_fixture}/flake.nix"
grep -qF 'home-manager/0.2611' "${available_fixture}/flake.nix"
grep -qF 'nixpkgs-26.11-chilled/0.1' "${available_fixture}/modules/outputs.nix"
grep -qF 'home-manager/0.2611' "${available_fixture}/modules/outputs.nix"
grep -qF 'nix --accept-flake-config flake update nixpkgs home-manager' "${MOCK_LOG}"

unavailable_fixture="${test_root}/unavailable"
make_fixture "${unavailable_fixture}"
export MOCK_LOG="${test_root}/unavailable.log"
export HOME_MANAGER_UPSTREAM_AVAILABLE=false
output_file="${test_root}/unavailable.output"
before="$(sha256sum "${unavailable_fixture}/flake.nix")"
PURPLEFIN_SOURCE_ROOT="${unavailable_fixture}" purplefin-update-home-release "${output_file}"
after="$(sha256sum "${unavailable_fixture}/flake.nix")"
grep -qFx 'changed=false' "${output_file}"
grep -qFx 'release=26.05' "${output_file}"
[[ "${before}" == "${after}" ]]
test ! -e "${MOCK_LOG}"
