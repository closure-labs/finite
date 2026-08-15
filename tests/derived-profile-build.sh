#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

delta="$({
	PURPLEFIN_BUILD_ROOT="${repo_root}/build_files" \
		PURPLEFIN_DERIVED_DRY_RUN=true \
		"${repo_root}/build_files/build-derived.sh" dale base-dell-xps-9350-intel
})"
test "${delta}" = $'sales\ntrainer\nsupport'

delta="$({
	PURPLEFIN_BUILD_ROOT="${repo_root}/build_files" \
		PURPLEFIN_DERIVED_DRY_RUN=true \
		"${repo_root}/build_files/build-derived.sh" support-generic base-generic
})"
test "${delta}" = support

if PURPLEFIN_BUILD_ROOT="${repo_root}/build_files" \
	PURPLEFIN_DERIVED_DRY_RUN=true \
	"${repo_root}/build_files/build-derived.sh" support-generic base-dell-xps-9350-intel >/dev/null 2>&1; then
	echo 'A derived profile accepted a parent with different hardware' >&2
	exit 1
fi
