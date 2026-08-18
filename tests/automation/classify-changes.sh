#!/usr/bin/env bash
set -euo pipefail

classify() {
	local component=$1
	shift
	printf '%s\n' "$@" | purplefin-classify-changes "${component}"
}

[[ "$(classify installer README.md docs/ci.md artifacts/bootc/generated/image-matrix.json)" == false ]]
[[ "$(classify installer installer/Containerfile)" == true ]]
[[ "$(classify installer installer/rootfs/usr/share/anaconda/interactive-defaults.ks)" == true ]]
[[ "$(classify installer .github/actions/build-installer/action.yml)" == true ]]
[[ "$(classify installer .github/workflows/build-installer.yml)" == true ]]
[[ "$(classify installer tests/installer/smoke.sh)" == true ]]
[[ "$(classify installer flake.lock)" == true ]]
[[ "$(classify installer .github/workflows/update-flake-lock.yml)" == false ]]
[[ "$(classify installer README.md installer/Containerfile docs/ci.md)" == true ]]

[[ "$(classify images README.md docs/ci.md .github/dependabot.yml)" == false ]]
[[ "$(classify images installer/Containerfile .github/workflows/build-installer.yml)" == false ]]
[[ "$(classify images .github/workflows/queue-dependabot.yml)" == false ]]
[[ "$(classify images .github/workflows/update-flake-lock.yml)" == false ]]
[[ "$(classify images .github/workflows/update-bluefin.yml .github/actions/setup-nix/action.yml)" == false ]]
[[ "$(classify images automation/github/classify-ci.sh tests/automation/classify-ci.sh secretspec.toml)" == false ]]
[[ "$(classify images npins/sources.json)" == true ]]
[[ "$(classify images bootc/Containerfile)" == true ]]
[[ "$(classify images .github/workflows/build-profile.yml)" == true ]]
[[ "$(classify images modules/aspects/base/apply.sh)" == true ]]
[[ "$(classify images flake.lock)" == true ]]
[[ "$(classify images README.md bootc/Containerfile docs/ci.md)" == true ]]

if purplefin-classify-changes unknown </dev/null; then
	echo 'unknown components must fail' >&2
	exit 1
fi
