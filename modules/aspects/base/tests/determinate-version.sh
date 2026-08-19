#!/usr/bin/env bash
set -euo pipefail

aspect_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
checker="${aspect_root}/rootfs/usr/libexec/purplefin/require-determinate-nix-version"
test_root="$(mktemp -d)"
trap 'rm -rf -- "${test_root}"' EXIT
nix_stub="${test_root}/nix"

{
	printf '#!%s\n' "$(type -P bash)"
	# The generated stub expands this variable when the test invokes it.
	# shellcheck disable=SC2016
	printf '%s\n' 'printf "%s\n" "${PURPLEFIN_TEST_NIX_VERSION:?}"'
} >"${nix_stub}"
chmod 0755 "${nix_stub}"

PURPLEFIN_TEST_NIX_VERSION='nix (Determinate Nix 3.21.9) 2.34.8' \
	bash "${checker}" 3.21.9 "${nix_stub}" >/dev/null
PURPLEFIN_TEST_NIX_VERSION='nix (Determinate Nix 3.22.0) 2.35.0' \
	bash "${checker}" 3.21.9 "${nix_stub}" >/dev/null

if PURPLEFIN_TEST_NIX_VERSION='nix (Determinate Nix 3.21.8) 2.34.8' \
	bash "${checker}" 3.21.9 "${nix_stub}" >/dev/null 2>&1; then
	echo 'An outdated Determinate Nix runtime was unexpectedly accepted' >&2
	exit 1
fi

if PURPLEFIN_TEST_NIX_VERSION='nix (Nix) 2.34.8' \
	bash "${checker}" 3.21.9 "${nix_stub}" >/dev/null 2>&1; then
	echo 'An upstream Nix runtime was unexpectedly accepted' >&2
	exit 1
fi
