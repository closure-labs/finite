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
output="${ISO_OUTPUT_DIR:-.bluebuild/iso}"
certificate=files/installer/secure-boot.pem
certificate_sha=$(jq -er .derSha256 sources/installer-security.json)
[[ $(jq -er .certificate sources/installer-security.json) == "$certificate" ]]
[[ $certificate_sha =~ ^[0-9a-f]{64}$ ]]
# Validate before pulling/building any container. The public certificate is
# retained in the checkout; neither availability nor trust depends on HTTP.
actual_certificate_sha=$(openssl x509 -in "$certificate" -outform DER | sha256sum | cut -d' ' -f1)
[[ $actual_certificate_sha == "$certificate_sha" ]]
openssl x509 -in "$certificate" -checkend 0 -noout
[[ $source =~ ^ghcr.io/jasonn3/build-container-installer@sha256:[0-9a-f]{64}$ ]]
[[ $alias == ghcr.io/jasonn3/build-container-installer:v1.4.0 ]]
# The pinned installer lacks OpenSSL. Convert on the validated host and copy
# only public installer inputs into a temporary build context.
installer_context=$(mktemp -d "${TMPDIR:-/tmp}/finite-installer-context.XXXXXX")
trap 'rm -rf -- "$installer_context"' EXIT
cp -a files/installer/. "$installer_context/"
openssl x509 -in "$certificate" -outform DER -out "$installer_context/secure-boot.der"
[[ $(sha256sum "$installer_context/secure-boot.der" | cut -d' ' -f1) == "$certificate_sha" ]]
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
docker build --pull=false --network=none --file "$installer_context/Containerfile" --build-arg "INSTALLER=$source" \
  --label "io.finite.installer-hook-sha256=$hook_sha" --tag "$alias" "$installer_context"
actual_hook_sha=$(docker run --rm --entrypoint sha256sum "$alias" \
  /build-container-installer/lorax_templates/scripts/post/install_finite_fstab | cut -d' ' -f1)
[[ $actual_hook_sha == "$hook_sha" ]]
installed_certificate_sha=$(docker run --rm --entrypoint sha256sum "$alias" \
  /build-container-installer/sb_pubkey.der | cut -d' ' -f1)
[[ $installed_certificate_sha == "$certificate_sha" ]]
image_id=$(docker inspect --format '{{.Id}}' "$alias")
mkdir -p "$output"
jq --arg resolved "$source" --arg id "$image_id" --arg hook "$hook" \
  --arg hash "$hook_sha" --arg revision "${GITHUB_SHA:?}" --arg certificate "$certificate_sha" \
  '. + {resolvedImage: $resolved, localImageId: $id, finiteRevision: $revision,
    secureBootCertificateSha256: $certificate, postInstallHook: {path: $hook, sha256: $hash}}' \
  "$lock" >"$output/installer.json"
