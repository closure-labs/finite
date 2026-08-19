#!/usr/bin/env bash
# shellcheck disable=SC2016,SC2251
set -euo pipefail

jq -e '
  .schema == 1 and
  .image == "ghcr.io/projectbluefin/bluefin" and
  .tag == "stable" and
  .architecture == "amd64" and
  (.digest | test("^sha256:[0-9a-f]{64}$")) and
  (.cosign.issuer | startswith("https://")) and
  (.cosign.identity | startswith("https://"))
' sources/bluefin.json >/dev/null
jq -e '
  .schema == 1 and
  .image == "ghcr.io/osbuild/image-builder-cli" and
  .tag == "latest" and
  .architecture == "amd64" and
  (.digest | test("^sha256:[0-9a-f]{64}$"))
' sources/image-builder.json >/dev/null
jq -e '
  .schema == 1 and
  .architecture == "x86_64-linux" and
  (.version | test("^[0-9]+\\.[0-9]+\\.[0-9]+$")) and
  (.installer.url | startswith("https://github.com/DeterminateSystems/nix-installer/releases/download/")) and
  (.installer.sha256 | test("^[0-9a-f]{64}$")) and
  (.selinuxPolicy.url | startswith("https://raw.githubusercontent.com/DeterminateSystems/nix-installer/")) and
  (.selinuxPolicy.sha256 | test("^[0-9a-f]{64}$"))
' sources/determinate-nix.json >/dev/null
secretspec schema --file secretspec.toml --profile local-cache |
  jq -e '.required == ["CACHIX_AUTH_TOKEN"]' >/dev/null
secretspec schema --file secretspec.toml --profile github-actions |
  jq -e '
    .required == [] and
    (.properties | keys == ["CACHIX_AUTH_TOKEN", "MERGE_QUEUE_TOKEN"])
  ' >/dev/null
grep -qF 'github-actions = "env"' secretspec.toml
grep -qF 'ref = { item = "GITHUB_ACTIONS_CACHIX_AUTH_TOKEN" }' secretspec.toml
grep -qF 'ref = { item = "GITHUB_ACTIONS_MERGE_QUEUE_TOKEN" }' secretspec.toml
! grep -qF 'cachix watch-exec' automation/nix/ci.sh
grep -qF 'cachix push --omit-deriver purplefin' automation/nix/ci.sh
grep -qF 'nix --accept-flake-config build --no-link' automation/nix/ci.sh
grep -qF 'max_closure_size=$((1024 * 1024))' automation/nix/ci.sh
! grep -qF 'dockerTools.pullImage' modules/outputs.nix
! grep -qF 'bluefin-upstream' modules/outputs.nix
grep -qF 'skopeo copy' automation/sources/load-bluefin.sh
grep -qF 'containers-storage:' automation/sources/load-bluefin.sh
grep -qF 'host_podman' automation/sources/load-bluefin.sh
grep -qF 'unshare "$0"' automation/sources/load-bluefin.sh
grep -qF 'https://purplefin.cachix.org' flake.nix
grep -qFx 'ARG BASE_REF' bootc/Containerfile
! grep -qF 'bluefin:stable' bootc/Containerfile
