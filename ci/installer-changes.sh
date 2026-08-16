#!/usr/bin/env bash
set -euo pipefail

required=false
while IFS= read -r path; do
	case "${path}" in
		.github/workflows/build-installer.yml | \
			.github/workflows/build.yml | \
			ci/installer-changes.sh | \
			flake.lock | \
			flake.nix | \
			installer/Containerfile | \
			installer/overlay/* | \
			nix/flake-modules/outputs.nix | \
			tests/boot-installer-iso.sh | \
			tests/installer-changes.sh)
			required=true
			break
			;;
	esac
done

printf '%s\n' "${required}"
