#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"

delta="$({
	PURPLEFIN_BUILD_ROOT="${repo_root}" \
		PURPLEFIN_DERIVED_DRY_RUN=true \
		bash "${repo_root}/bootc/builder/derived.sh" base-generic base
})"
test "${delta}" = hardware-generic-x86_64

delta="$({
	PURPLEFIN_BUILD_ROOT="${repo_root}" \
		PURPLEFIN_DERIVED_DRY_RUN=true \
		bash "${repo_root}/bootc/builder/derived.sh" dale base-dell-xps-9350-intel
})"
test "${delta}" = $'devops\nsales\ntrainer\nsupport'

delta="$({
	PURPLEFIN_BUILD_ROOT="${repo_root}" \
		PURPLEFIN_DERIVED_DRY_RUN=true \
		bash "${repo_root}/bootc/builder/derived.sh" support-generic base-generic
})"
test "${delta}" = $'devops\nsupport'

if PURPLEFIN_BUILD_ROOT="${repo_root}" \
	PURPLEFIN_DERIVED_DRY_RUN=true \
	bash "${repo_root}/bootc/builder/derived.sh" support-generic base-dell-xps-9350-intel >/dev/null 2>&1; then
	echo 'A derived profile accepted a parent with different hardware' >&2
	exit 1
fi
