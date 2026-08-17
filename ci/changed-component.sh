#!/usr/bin/env bash
set -euo pipefail

component="${1:?usage: changed-component.sh COMPONENT}"
required=false

case "${component}" in
	images | installer) ;;
	*)
		echo "unknown component: ${component}" >&2
		exit 2
		;;
esac

while IFS= read -r path; do
	case "${component}:${path}" in
		installer:.github/actions/build-installer/* | \
		installer:.github/workflows/build-installer.yml | \
		installer:.github/workflows/build.yml | \
		installer:ci/changed-component.sh | \
		installer:flake.lock | \
		installer:flake.nix | \
		installer:installer/Containerfile | \
		installer:installer/overlay/* | \
		installer:nix/flake-modules/outputs.nix | \
		installer:tests/boot-installer-iso.sh | \
		installer:tests/changed-component.sh)
			required=true
			break
			;;
		images:README.md | \
		images:LICENSE | \
		images:docs/* | \
		images:.editorconfig | \
		images:.github/actions/build-installer/* | \
		images:.github/dependabot.yml | \
		images:.github/workflows/build-installer.yml | \
		images:.github/workflows/cleanup.yml | \
		images:.github/workflows/queue-dependabot.yml | \
		images:.github/workflows/release.yml | \
		images:.github/workflows/update-flake-lock.yml | \
		images:.github/workflows/update-image-builder.yml | \
		images:ci/changed-component.sh | \
		images:ci/validate-trusted-update.sh | \
		images:installer/* | \
		images:tests/boot-installer-iso.sh | \
		images:tests/changed-component.sh | \
		images:tests/text-style.sh | \
		images:tests/trusted-update-validation.sh)
			;;
		images:*)
			required=true
			break
			;;
	esac
done

printf '%s\n' "${required}"
