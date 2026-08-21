#!/usr/bin/env bash
set -euo pipefail

ready_dropin=installer/rootfs/usr/lib/systemd/system/anaconda.service.d/purplefin-ready.conf
kickstart="$(mktemp)"
trap 'rm -f -- "${kickstart}"' EXIT

test -f "${ready_dropin}"
grep -qFx '[Service]' "${ready_dropin}"
grep -qF 'ExecStartPost=' "${ready_dropin}"
grep -qF 'PURPLEFIN_INSTALLER_READY=1' "${ready_dropin}"
grep -qF '[customizations.installer.kickstart]' installer/ci-unattended.toml.in
grep -qF 'PURPLEFIN_INSTALLED_READY=1' installer/ci-unattended.toml.in
grep -qF 'bootc --source-imgref registry:@@INSTALLER_PAYLOAD_SOURCE_REF@@' \
	installer/ci-unattended.toml.in
sed -n '/^contents = """$/,/^"""$/p' installer/ci-unattended.toml.in |
	sed '1d;$d' >"${kickstart}"
ksvalidator "${kickstart}"
grep -qF "ready_marker='PURPLEFIN_INSTALLER_READY=1'" \
	lib/ci-applications/installer-smoke.nix
grep -qF "ready_marker='PURPLEFIN_INSTALLED_READY=1'" \
	lib/ci-applications/installer-e2e.nix
grep -qF 'PURPLEFIN_INSTALLER_E2E_INSTALL_TIMEOUT_SECONDS:-3600' \
	lib/ci-applications/installer-e2e.nix
grep -qF -- '--bootc-ref' lib/installer-application.nix
grep -qF -- '--bootc-installer-payload-ref' lib/installer-application.nix
grep -qF -- '--build-context installer-rootfs=installer/rootfs' \
	lib/installer-application.nix
grep -qF -- '--security-opt label=disable' lib/installer-application.nix
grep -qF 'PURPLEFIN_INSTALLER_BASE_REF' lib/installer-application.nix
grep -qF 'purplefin-installer-environment-v2' lib/installer-application.nix
grep -qF -- '--build-arg "BASE_REF=' lib/installer-application.nix
grep -qF 'ARG BASE_REF=quay.io/fedora/fedora-bootc:44' installer/Containerfile
grep -qF 'certificate-identity-regexp' lib/installer-application.nix
grep -qF 'workflows/(build|build-installer)' lib/installer-application.nix
grep -qF -- '--blueprint /purplefin-ci-unattended.toml' lib/installer-application.nix
grep -qF -- '--cache /var/cache/image-builder/store' lib/installer-application.nix
grep -qF -- '--rpmmd-cache /var/cache/image-builder/rpmmd' lib/installer-application.nix
test -x installer/osbuild-stages/org.osbuild.squashfs
jq -e --slurpfile image_builder sources/image-builder.json '
  .schema == 1 and
  .image_builder_digest == $image_builder[0].digest and
  (.override_sha256 | test("^[0-9a-f]{64}$")) and
  (.upstream_sha256 | test("^[0-9a-f]{64}$")) and
  .zstd_compression_level == 1
' installer/osbuild-stages/lock.json >/dev/null
locked_override_sha256="$(jq -r .override_sha256 installer/osbuild-stages/lock.json)"
actual_override_sha256="$(sha256sum installer/osbuild-stages/org.osbuild.squashfs | cut -d' ' -f1)"
[[ "${actual_override_sha256}" == "${locked_override_sha256}" ]]
grep -qF 'DEFAULT_ZSTD_COMPRESSION_LEVEL = "1"' \
	installer/osbuild-stages/org.osbuild.squashfs
grep -qF -- '-Xcompression-level' installer/osbuild-stages/org.osbuild.squashfs
mount_count="$(grep -cF 'osbuild/stages/org.osbuild.squashfs:ro' lib/installer-application.nix)"
[[ "${mount_count}" == 2 ]]
grep -qF 'RUN --mount=from=installer-rootfs,target=/run/installer-rootfs' \
	installer/Containerfile
