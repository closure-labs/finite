#!/usr/bin/env bash
set -euo pipefail

classify() {
	printf '%s\n' "$@" | ci/installer-changes.sh
}

[[ "$(classify README.md docs/ci.md bootc/generated/image-matrix.json)" == false ]]
[[ "$(classify installer/Containerfile)" == true ]]
[[ "$(classify installer/overlay/usr/share/anaconda/interactive-defaults.ks)" == true ]]
[[ "$(classify .github/actions/build-installer/action.yml)" == true ]]
[[ "$(classify .github/workflows/build-installer.yml)" == true ]]
[[ "$(classify tests/boot-installer-iso.sh)" == true ]]
[[ "$(classify flake.lock)" == true ]]
[[ "$(classify README.md installer/Containerfile docs/ci.md)" == true ]]
