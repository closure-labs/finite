#!/usr/bin/env bash
set -euo pipefail

test_root=$(mktemp -d)
trap 'rm -rf "$test_root"' EXIT
mkdir -p "$test_root/sources"
cp sources/determinate-nix.json "$test_root/sources/"
touch "$test_root/flake.nix"
export FINITE_SOURCE_ROOT=$test_root
export GITHUB_ACTIONS=true GH_TOKEN=fixture
export MOCK_VERSION=9.9.9
export MOCK_MODE=valid

python3() {
	if [[ "$*" == *api.github.com* ]]; then
		[[ "$MOCK_MODE" != network ]] || return 1
		if [[ "$MOCK_MODE" == malformed ]]; then
			printf '{}'
			return
		fi
		jq -n --arg version "$MOCK_VERSION" '{draft:false, prerelease:false, tag_name:("v" + $version), assets:[{name:"nix-installer-x86_64-linux", browser_download_url:("https://github.com/DeterminateSystems/nix-installer/releases/download/v" + $version + "/nix-installer-x86_64-linux"), digest:("sha256:" + ("a" * 64))}]}'
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

# A newer installer cannot silently replace the pinned native-runtime baseline.
mkdir -p "$test_root/lib"
touch "$test_root/lib/native-nix-backport.nix"
rm "$test_root/output"
before=$(sha256sum "$test_root/sources/determinate-nix.json")
export MOCK_VERSION=9.9.10
if finite-source-update determinate-nix "$test_root/output" 2>"$test_root/error"; then
	exit 1
else
	status=$?
fi
[[ "$status" == 5 ]]
grep -qF 'requires a coordinated native runtime update' "$test_root/error"
[[ "$(sha256sum "$test_root/sources/determinate-nix.json")" == "$before" ]]
[[ ! -e "$test_root/output" ]]
# The same version remains idempotent while the backport is present.
export MOCK_VERSION=9.9.9
finite-source-update determinate-nix "$test_root/output"
grep -qFx 'changed=false' "$test_root/output"
# Removing the backport in a separately validated change permits updates again.
rm "$test_root/lib/native-nix-backport.nix" "$test_root/output"
export MOCK_VERSION=9.9.10
finite-source-update determinate-nix "$test_root/output"
grep -qFx 'changed=true' "$test_root/output"
