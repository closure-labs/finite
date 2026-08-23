#!/usr/bin/env bash
set -euo pipefail

classify() {
	local component=$1
	shift
	printf '%s\n' "$@" | finite-classify-changes "${component}"
}

[[ "$(classify installer README.md docs/ci.md artifacts/bootc/generated/image-matrix.json)" == false ]]
[[ "$(classify installer installer/live/finite/recipe.json)" == true ]]
[[ "$(classify installer installer/prepare-bluefin-iso-source)" == true ]]
[[ "$(classify installer .github/actions/build-installer/action.yml)" == true ]]
[[ "$(classify installer .github/workflows/build-installer.yml)" == false ]]
[[ "$(classify installer .github/workflows/build.yml)" == false ]]
[[ "$(classify installer .github/actions/setup-nix/action.yml)" == false ]]
[[ "$(classify installer tests/installer/smoke.sh)" == false ]]
[[ "$(classify installer flake.lock)" == true ]]
[[ "$(classify installer .github/workflows/update-flake-lock.yml)" == false ]]
[[ "$(classify installer README.md installer/live/finite/images.json docs/ci.md)" == true ]]

[[ "$(classify images README.md docs/ci.md .github/dependabot.yml)" == false ]]
[[ "$(classify images installer/live/finite/images.json .github/workflows/build-installer.yml)" == false ]]
[[ "$(classify images .github/workflows/queue-dependabot.yml)" == false ]]
[[ "$(classify images .github/workflows/update-flake-lock.yml)" == false ]]
[[ "$(classify images .github/workflows/update-bluefin.yml)" == false ]]
[[ "$(classify images .github/actions/setup-nix/action.yml)" == true ]]
[[ "$(classify images tests/automation/classify-ci.sh secretspec.toml)" == false ]]
[[ "$(classify images sources/bluefin.json)" == true ]]
[[ "$(classify installer sources/bluefin-installer.json)" == true ]]
[[ "$(classify installer sources/determinate-nix.json)" == false ]]
[[ "$(classify installer lib/ci-applications/installer-e2e.nix)" == true ]]
[[ "$(classify installer lib/ci-applications/installer-smoke.nix)" == true ]]
[[ "$(classify installer lib/installer-application.nix)" == true ]]
[[ "$(classify installer lib/render-profile-artifacts.nix)" == false ]]
[[ "$(classify installer lib/flake-applications.nix)" == false ]]
[[ "$(classify installer modules/outputs.nix)" == false ]]
[[ "$(classify installer modules/profiles/definitions.nix)" == false ]]
[[ "$(classify installer modules/sources/oci-locks.nix)" == false ]]
[[ "$(classify installer lib/ci-applications/image-sign.nix)" == false ]]
[[ "$(classify installer lib/repository-checks.nix)" == false ]]
[[ "$(classify installer modules/aspects/base/apply.sh)" == false ]]
[[ "$(classify installer modules/aspects/base/tests/contracts.sh)" == false ]]
[[ "$(classify images sources/determinate-nix.json)" == true ]]
[[ "$(classify images .github/workflows/update-determinate-nix.yml)" == false ]]
[[ "$(classify images bootc/Containerfile)" == true ]]
[[ "$(classify images .github/workflows/build-profile.yml)" == true ]]
[[ "$(classify images modules/aspects/base/apply.sh)" == true ]]
[[ "$(classify images modules/aspects/base/tests/contracts.sh)" == false ]]
[[ "$(classify images tests/bootc/plan.sh)" == false ]]
[[ "$(classify images tests/repository/contracts.sh)" == false ]]
[[ "$(classify images lib/installer-application.nix)" == false ]]
[[ "$(classify images lib/repository-checks.nix)" == false ]]
[[ "$(classify images flake.lock)" == true ]]
[[ "$(classify images README.md bootc/Containerfile docs/ci.md)" == true ]]

if finite-classify-changes unknown </dev/null; then
	echo 'unknown components must fail' >&2
	exit 1
fi
