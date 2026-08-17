#!/usr/bin/env bash
set -euo pipefail

classify() {
	local component=$1
	shift
	printf '%s\n' "$@" | ci/changed-component.sh "${component}"
}

[[ "$(classify installer README.md docs/ci.md bootc/generated/image-matrix.json)" == false ]]
[[ "$(classify installer installer/Containerfile)" == true ]]
[[ "$(classify installer installer/overlay/usr/share/anaconda/interactive-defaults.ks)" == true ]]
[[ "$(classify installer .github/actions/build-installer/action.yml)" == true ]]
[[ "$(classify installer .github/workflows/build-installer.yml)" == true ]]
[[ "$(classify installer tests/boot-installer-iso.sh)" == true ]]
[[ "$(classify installer flake.lock)" == true ]]
[[ "$(classify installer .github/workflows/update-flake-lock.yml)" == false ]]
[[ "$(classify installer README.md installer/Containerfile docs/ci.md)" == true ]]

[[ "$(classify images README.md docs/ci.md .github/dependabot.yml)" == false ]]
[[ "$(classify images installer/Containerfile .github/workflows/build-installer.yml)" == false ]]
[[ "$(classify images .github/workflows/queue-dependabot.yml)" == false ]]
[[ "$(classify images .github/workflows/update-flake-lock.yml)" == false ]]
[[ "$(classify images Containerfile)" == true ]]
[[ "$(classify images .github/workflows/build-profile.yml)" == true ]]
[[ "$(classify images bootc/components/base/packages.txt)" == true ]]
[[ "$(classify images flake.lock)" == true ]]
[[ "$(classify images README.md Containerfile docs/ci.md)" == true ]]

if ci/changed-component.sh unknown </dev/null; then
	echo 'unknown components must fail' >&2
	exit 1
fi
