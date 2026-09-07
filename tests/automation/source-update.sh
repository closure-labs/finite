#!/usr/bin/env bash
set -euo pipefail

test_root=$(mktemp -d)
trap 'rm -rf "$test_root"' EXIT
mkdir -p "$test_root/sources"
cp sources/determinate-nix.json "$test_root/sources/"
touch "$test_root/flake.nix"
export FINITE_SOURCE_ROOT=$test_root
export GITHUB_ACTIONS=true GH_TOKEN=fixture
export MOCK_MODE=valid

python3() {
	if [[ "$*" == *api.github.com* ]]; then
		[[ "$MOCK_MODE" != network ]] || return 1
		if [[ "$MOCK_MODE" == malformed ]]; then
			printf '{}'
			return
		fi
		jq -n '{draft:false, prerelease:false, tag_name:"v9.9.9", assets:[{name:"nix-installer-x86_64-linux", browser_download_url:"https://github.com/DeterminateSystems/nix-installer/releases/download/v9.9.9/nix-installer-x86_64-linux", digest:("sha256:" + ("a" * 64))}]}'
	else
		[[ "$MOCK_MODE" != download ]] || return 1
		if [[ "$MOCK_MODE" == empty ]]; then
			: >"$3"
		else
			printf 'policy fixture\n' >"$3"
		fi
	fi
}
export -f python3

for mode in missing-token malformed network download empty; do
	export MOCK_MODE=$mode
	before=$(sha256sum "$test_root/sources/determinate-nix.json")
	if [[ "$mode" == missing-token ]]; then
		if GH_TOKEN= GITHUB_TOKEN= finite-source-update determinate-nix "$test_root/output"; then exit 1; fi
	else
		if finite-source-update determinate-nix "$test_root/output"; then exit 1; fi
	fi
	[[ "$(sha256sum "$test_root/sources/determinate-nix.json")" == "$before" ]]
	[[ ! -e "$test_root/output" ]]
done
export MOCK_MODE=valid
finite-source-update determinate-nix "$test_root/output"
grep -qFx 'changed=true' "$test_root/output"
: >"$test_root/output"
finite-source-update determinate-nix "$test_root/output"
grep -qFx 'changed=false' "$test_root/output"
