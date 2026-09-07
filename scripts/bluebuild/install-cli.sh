#!/usr/bin/env bash
set -euo pipefail
source=$(jq -er '.image + "@" + .digest' sources/bluebuild-cli.json)
version=$(jq -er .version sources/bluebuild-cli.json)
[[ $source =~ ^ghcr.io/blue-build/cli@sha256:[0-9a-f]{64}$ ]]
cosign verify --key sources/bluebuild-cli.pub "$source" >/dev/null
directory=$(mktemp -d)
trap 'docker rm finite-bluebuild-cli >/dev/null 2>&1 || true; rm -rf "$directory"' EXIT
docker create --name finite-bluebuild-cli "$source"
docker cp finite-bluebuild-cli:/out/bluebuild "$directory/bluebuild"
actual_version=$("$directory/bluebuild" --version)
printf '%s\n' "$actual_version"
if [[ ${actual_version%%$'\n'*} != "BlueBuild ${version#v}" ]]; then
  printf 'Expected BlueBuild %s from locked installer\n' "${version#v}" >&2
  exit 1
fi
sudo install -m 0755 "$directory/bluebuild" /usr/local/bin/bluebuild
