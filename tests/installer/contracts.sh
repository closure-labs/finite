#!/usr/bin/env bash
set -euo pipefail

installer_build="${1:?usage: contracts.sh INSTALLER_BUILD}"
ready_dropin=installer/rootfs/usr/lib/systemd/system/anaconda.service.d/finite-ready.conf
kickstart="$(mktemp)"
trap 'rm -f -- "${kickstart}"' EXIT

test -f "${ready_dropin}"
grep -qFx '[Service]' "${ready_dropin}"
grep -qF 'ExecStartPost=' "${ready_dropin}"
grep -qF 'FINITE_INSTALLER_READY=1' "${ready_dropin}"
grep -qF 'text --non-interactive' installer/ci-unattended.ks.in
grep -qF 'FINITE_INSTALLED_READY=1' installer/ci-unattended.ks.in
grep -qF 'bootc --source-imgref registry:@@INSTALLER_PAYLOAD_SOURCE_REF@@' \
	installer/ci-unattended.ks.in
grep -qF -- '--target-imgref @@INSTALLER_PAYLOAD_TARGET_REF@@' \
	installer/ci-unattended.ks.in
grep -qF 'status --json --format-version=1' installer/ci-unattended.ks.in
grep -qF 'Before=finite-firstboot-rpm-ostree.service' \
	installer/ci-unattended.ks.in
grep -qF 'StandardError=journal+console' installer/ci-unattended.ks.in
grep -qF 'image["imageDigest"]' installer/ci-unattended.ks.in
grep -qF 'image["image"]["image"]' installer/ci-unattended.ks.in
grep -qF 'FINITE_INSTALLED_ERROR=digest-mismatch' installer/ci-unattended.ks.in
grep -qF 'FINITE_INSTALLED_ERROR=reference-mismatch' installer/ci-unattended.ks.in
cp installer/ci-unattended.ks.in "${kickstart}"
ksvalidator "${kickstart}"
grep -qF "ready_marker='FINITE_INSTALLER_READY=1'" \
	lib/ci-applications/installer-smoke.nix
grep -qF "ready_marker='FINITE_INSTALLED_READY=1'" \
	lib/ci-applications/installer-e2e.nix
grep -qF 'FINITE_INSTALLER_E2E_KICKSTART_TIMEOUT_SECONDS:-180' \
	lib/ci-applications/installer-e2e.nix
grep -qF 'FINITE_INSTALLER_E2E_INSTALL_TIMEOUT_SECONDS:-1200' \
	lib/ci-applications/installer-e2e.nix
grep -qF 'FINITE_INSTALLER_E2E_BOOT_TIMEOUT_SECONDS:-180' \
	lib/ci-applications/installer-e2e.nix
grep -qF -- '--bootc-ref' lib/installer-application.nix
grep -qF -- '--bootc-installer-payload-ref' lib/installer-application.nix
grep -qF -- "--bootc-installer-payload-ref \"''\${payload_update_ref}\"" \
	lib/installer-application.nix
grep -qF "pull \"''\${auth_args[@]}\" \"''\${payload_ref}\"" \
	lib/installer-application.nix
grep -qF "GHCR_TOKEN is required to read the Finite payload" \
	lib/installer-application.nix
grep -qF "auth_args=(--authfile \"''\${registry_auth_file}\")" \
	lib/installer-application.nix
attestation_auth_count="$(
	grep -cF "DOCKER_CONFIG=\"''\${cosign_config_dir}\" gh attestation verify" \
		lib/installer-application.nix
)"
[[ "${attestation_auth_count}" == 2 ]]
if grep -B2 -F "auth_args=(--authfile \"''\${registry_auth_file}\")" \
	lib/installer-application.nix | grep -qF 'CACHE_WRITE'; then
	echo 'Installer payload authentication is conditional on cache writes' >&2
	exit 1
fi
grep -qF "tag \"''\${payload_ref}\" \"''\${payload_update_ref}\"" \
	lib/installer-application.nix
grep -qF -- '--build-context installer-rootfs=installer/rootfs' \
	lib/installer-application.nix
grep -qF -- '--security-opt label=disable' lib/installer-application.nix
grep -qF 'FINITE_INSTALLER_BASE_REF' lib/installer-application.nix
grep -qF 'finite-installer-environment-v3' lib/installer-application.nix
grep -qF 'schema_version: 2' lib/installer-application.nix
# The literal jq variable names are part of the generated manifest expression.
# shellcheck disable=SC2016
grep -qF 'embedded_reference: $payload_embedded_reference' lib/installer-application.nix
# shellcheck disable=SC2016
grep -qF 'update_reference: $payload_update_reference' lib/installer-application.nix
grep -qF 'profile-tag=' lib/installer-application.nix
if grep -A8 -F 'finite-installer-environment-v3' lib/installer-application.nix |
	grep -qF 'payload_digest'; then
	echo 'Installer environment cache identity depends on the payload digest' >&2
	exit 1
fi
grep -qF -- '--build-arg "BASE_REF=' lib/installer-application.nix
grep -qF -- '--build-arg "INSTALLER_CONTEXT_DIGEST=' \
	lib/installer-application.nix
grep -qF 'ARG INSTALLER_CONTEXT_DIGEST' installer/Containerfile
# shellcheck disable=SC2016
grep -qF 'test -n "${INSTALLER_CONTEXT_DIGEST}"' installer/Containerfile
grep -qF 'ARG BASE_REF=quay.io/fedora/fedora-bootc:44' installer/Containerfile
grep -qF 'certificate-identity-regexp' lib/installer-application.nix
grep -qF 'workflows/(build|build-installer)' lib/installer-application.nix
grep -qF 'installer/ci-unattended.ks.in' lib/installer-application.nix
grep -qF 'inst.ks=http://10.0.2.2:' lib/ci-applications/installer-e2e.nix
grep -qF -- '-kernel "' lib/ci-applications/installer-e2e.nix
if grep -qF -- '--blueprint' lib/installer-application.nix; then
	exit 1
fi
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
[[ "${mount_count}" == 1 ]]
grep -qF 'RUN --mount=from=installer-rootfs,target=/run/installer-rootfs' \
	installer/Containerfile

for phase in \
	'Build installer environment and ISO' \
	'Smoke-test installer ISO bootloader' \
	'Perform unattended installation' \
	'Boot and validate installed system' \
	'Upload installer diagnostics'; do
	grep -qF -- "- name: ${phase}" .github/actions/build-installer/action.yml
done
grep -qF 'iso-path=' lib/installer-application.nix
grep -qF 'kickstart-path=' lib/installer-application.nix
if grep -A20 '^outputs:' .github/actions/build-installer/action.yml |
	grep -Eq '^  (iso-path|kickstart-path):'; then
	echo 'Internal installer paths leaked into the composite action output contract' >&2
	exit 1
fi

base='quay.io/fedora/fedora-bootc@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
context_a='1111111111111111111111111111111111111111111111111111111111111111'
context_b='2222222222222222222222222222222222222222222222222222222222222222'
tag_a='ghcr.io/example/finite:bluefin-generic'
tag_b='ghcr.io/example/finite:base-dell-xps-9350-intel'
export FINITE_TEST_PAYLOAD_DIGEST=sha256:aaaa
key_a="$(${installer_build} cache-input "${base}" "${context_a}" "${tag_a}")"
export FINITE_TEST_PAYLOAD_DIGEST=sha256:bbbb
key_same="$(${installer_build} cache-input "${base}" "${context_a}" "${tag_a}")"
unset FINITE_TEST_PAYLOAD_DIGEST
key_context="$(${installer_build} cache-input "${base}" "${context_b}" "${tag_a}")"
key_tag="$(${installer_build} cache-input "${base}" "${context_a}" "${tag_b}")"
[[ "${key_a}" == "${key_same}" ]]
[[ "${key_a}" != "${key_context}" ]]
[[ "${key_a}" != "${key_tag}" ]]
