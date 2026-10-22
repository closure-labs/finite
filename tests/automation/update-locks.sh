#!/usr/bin/env bash
set -euo pipefail

test_root=$(mktemp -d)
trap 'rm -rf "$test_root"' EXIT
export FINITE_SOURCE_ROOT=$test_root
export MOCK_NEWLINE=false MOCK_INVALID=false
touch "$test_root/flake.nix"
printf '%s\n' '{"inputs":{"devenv":{"url":"github:cachix/devenv"}},"secretspec":{"enable":true,"provider":"keyring","cachix_auth_token":true}}' >"$test_root/devenv.yaml"
export CACHIX_AUTH_TOKEN=fixture-cache MERGE_QUEUE_TOKEN=fixture-updater
export MOCK_UPDATE_ROOT_FILE="$test_root/update-root"
printf '{}\n' >"$test_root/flake.lock"
printf '{}\n' >"$test_root/devenv.lock"

nix() {
	[[ -z "${CACHIX_AUTH_TOKEN+x}" && -z "${MERGE_QUEUE_TOKEN+x}" ]] || return 1
	printf '{"nodes": {}}\n' >flake.lock
}
devenv() {
	[[ "$*" == update ]] || return 1
	[[ -z "${CACHIX_AUTH_TOKEN+x}" && -z "${MERGE_QUEUE_TOKEN+x}" ]] || return 1
	[[ "$PWD" != "$FINITE_SOURCE_ROOT" && ! -e secretspec.toml ]] || return 1
	jq -e '.secretspec == {"enable":false} and .inputs.devenv.url == "github:cachix/devenv"' devenv.yaml >/dev/null || return 1
	printf '%s\n' "$PWD" >"$MOCK_UPDATE_ROOT_FILE"
	if [[ "$MOCK_INVALID" == true ]]; then
		printf 'broken' >devenv.lock
	else
		printf '{"nodes": {}}' >devenv.lock
		if [[ "$MOCK_NEWLINE" == true ]]; then printf '\n' >>devenv.lock; fi
	fi
}
export -f nix devenv
finite-update-locks "$test_root/output"
[[ ! -e "$(cat "$MOCK_UPDATE_ROOT_FILE")" ]]
[[ "$CACHIX_AUTH_TOKEN" == fixture-cache && "$MERGE_QUEUE_TOKEN" == fixture-updater ]]
grep -qFx 'changed=true' "$test_root/output"
printf '{"nodes": {}}\n' >"$test_root/expected"
cmp "$test_root/expected" "$test_root/devenv.lock"
first_digest=$(sed -n 's/^digest=//p' "$test_root/output")
for newline in false true; do
	export MOCK_NEWLINE=$newline
	: >"$test_root/output"
	finite-update-locks "$test_root/output"
	[[ ! -e "$(cat "$MOCK_UPDATE_ROOT_FILE")" ]]
	[[ "$CACHIX_AUTH_TOKEN" == fixture-cache && "$MERGE_QUEUE_TOKEN" == fixture-updater ]]
	grep -qFx 'changed=false' "$test_root/output"
	grep -qFx "digest=$first_digest" "$test_root/output"
	jq -e 'type == "object"' "$test_root/devenv.lock" >/dev/null
done
export GITHUB_ACTIONS=true
: >"$test_root/output"
finite-update-locks "$test_root/output"
[[ ! -e "$(cat "$MOCK_UPDATE_ROOT_FILE")" ]]
[[ "$CACHIX_AUTH_TOKEN" == fixture-cache && "$MERGE_QUEUE_TOKEN" == fixture-updater ]]
grep -qFx 'changed=false' "$test_root/output"
export MOCK_INVALID=true
: >"$test_root/output"
if finite-update-locks "$test_root/output"; then exit 1; fi
[[ ! -s "$test_root/output" ]]
[[ ! -e "$(cat "$MOCK_UPDATE_ROOT_FILE")" ]]
jq -e '.secretspec.enable == true and .secretspec.cachix_auth_token == true' "$test_root/devenv.yaml" >/dev/null
