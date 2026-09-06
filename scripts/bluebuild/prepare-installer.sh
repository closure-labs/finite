#!/usr/bin/env bash
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} == true && ${GITHUB_REPOSITORY:-} == closure-labs/finite ]] || {
  echo 'Prepare the installer only on the ephemeral finite ISO runner.' >&2
  exit 2
}
lock=sources/bluebuild-installer.json
source=$(jq -er '.image + "@" + .digest' "$lock")
alias=$(jq -er .cliAlias "$lock")
version=$(jq -er .version "$lock")
revision=$(jq -er .revision "$lock")
[[ $source =~ ^ghcr.io/jasonn3/build-container-installer@sha256:[0-9a-f]{64}$ ]]
[[ $alias == ghcr.io/jasonn3/build-container-installer:v1.4.0 ]]
docker pull "$source"
docker inspect "$source" | jq -e --arg version "$version" --arg revision "$revision" '
  .[0].Config.Labels |
  .["org.opencontainers.image.version"] == $version and
  .["org.opencontainers.image.revision"] == $revision
' >/dev/null
# Old Lorax strips these executables although newer Anaconda needs load_policy
# to restore the installer SELinux policy before shutdown (RHEL-144456).
docker run --rm --entrypoint /bin/bash "$source" -euo pipefail -c '
  template=/usr/share/lorax/templates.d/99-generic/runtime-cleanup.tmpl
  rpm -q lorax
  grep -q "^removefrom policycoreutils " "$template"
  if grep -E "^removefrom policycoreutils .*usr/(bin|sbin|\\*bin)" "$template"; then
    echo "Installer cleanup would remove the SELinux policy loader" >&2
    exit 1
  fi
'
# Use the upstream install_* hook mechanism to finalize the physical root fstab.
# CLI v0.9.37 has no installer-image option, so the result uses its local alias.
hook=files/installer/install_finite_fstab
hook_sha=$(sha256sum "$hook" | cut -d' ' -f1)
printf 'Using installer %s (%s) through local CLI compatibility alias %s\n' "$version" "$source" "$alias"
docker build --pull=false --network=none --file files/installer/Containerfile --build-arg "INSTALLER=$source" \
  --label "io.finite.installer-hook-sha256=$hook_sha" --tag "$alias" files/installer
actual_hook_sha=$(docker run --rm --entrypoint sha256sum "$alias" \
  /build-container-installer/lorax_templates/scripts/post/install_finite_fstab | cut -d' ' -f1)
[[ $actual_hook_sha == "$hook_sha" ]]
image_id=$(docker inspect --format '{{.Id}}' "$alias")
mkdir -p .bluebuild/iso
jq --arg resolved "$source" --arg id "$image_id" --arg hook "$hook" \
  --arg hash "$hook_sha" --arg revision "${GITHUB_SHA:?}" \
  '. + {resolvedImage: $resolved, localImageId: $id, finiteRevision: $revision,
    postInstallHook: {path: $hook, sha256: $hash}}' \
  "$lock" >.bluebuild/iso/installer.json
