#!/usr/bin/env bash
set -euo pipefail

installer_build="${1:?usage: contracts.sh INSTALLER_BUILD}"

jq -e '
  .schema == 2 and
  (.iso_source.owner == "projectbluefin") and
  (.iso_source.repository == "dakota-iso") and
  (.iso_source.revision | test("^[0-9a-f]{40}$")) and
  (.iso_source.hash | startswith("sha256-")) and
  (.installer.version | test("^[0-9]+\\.[0-9]+\\.[0-9]+$")) and
  (.installer.url | startswith("https://github.com/projectbluefin/bootc-installer/releases/download/")) and
  (.installer.sha256 | test("^[0-9a-f]{64}$")) and
  (.builder.image == "docker.io/library/debian") and
  (.builder.tag == "bookworm") and
  (.builder.architecture == "amd64") and
  (.builder.digest | test("^sha256:[0-9a-f]{64}$")) and
  (.image_builder.version | test("^[0-9]+\\.[0-9]+\\.[0-9]+$")) and
  .image_builder.image == "ghcr.io/osbuild/image-builder-cli" and
  .image_builder.architecture == "amd64" and
  (.image_builder.digest | test("^sha256:[0-9a-f]{64}$"))
' sources/bluefin-installer.json >/dev/null

test -x installer/prepare-bluefin-iso-source
test -x installer/live/finite/configure-live.d.sh
for file in images.json recipe.json ci-autoinstall.json; do
	jq -e . "installer/live/finite/${file}" >/dev/null
done
grep -qFx 'grub' installer/live/finite/bootloader
grep -qFx 'false' installer/live/finite/composefs
grep -qF '@@UPDATE_REFERENCE@@' installer/live/finite/images.json
grep -qF '@@UPDATE_REFERENCE@@' installer/live/finite/ci-autoinstall.json
grep -qF '"disk": "/dev/vda"' installer/live/finite/ci-autoinstall.json
grep -qF '"filesystem": "btrfs"' installer/live/finite/ci-autoinstall.json
grep -qF 'FINITE_INSTALLER_READY=1' installer/live/finite/configure-live.d.sh
grep -qF 'FINITE_INSTALLER_COMPLETE=1' installer/live/finite/configure-live.d.sh
grep -qF 'FINITE_INSTALLED_READY=1' installer/live/finite/configure-live.d.sh
grep -qF 'finite.installer.autoinstall=1' installer/live/finite/configure-live.d.sh
grep -qF 'Installation complete!' installer/live/finite/configure-live.d.sh
grep -qF 'Installation failed!' installer/live/finite/configure-live.d.sh
grep -qF 'root-mount-spec = "LABEL=root"' installer/live/finite/bootc-install-defaults.toml
cmp -s \
	installer/live/finite/bootc-install-defaults.toml \
	modules/aspects/base/rootfs/usr/lib/bootc/install/00-defaults.toml
grep -qF '/usr/lib/bootc/install/00-defaults.toml' installer/live/finite/configure-live.d.sh
# Literal generated-script contract.
# shellcheck disable=SC2016
grep -qF 'flatpak kill "${app_id}"' installer/live/finite/configure-live.d.sh
grep -qF 'installer-debug.log' installer/live/finite/configure-live.d.sh
grep -qF 'label: FINITE_LIVE' installer/live/finite/iso.yaml
grep -qF 'root=live:LABEL=FINITE_LIVE' installer/live/finite/iso.yaml
grep -qF 'linux: /images/pxeboot/vmlinuz' installer/live/finite/iso.yaml
grep -qF 'Image Builder embeds the verified payload' installer/prepare-bluefin-iso-source
test ! -e installer/image-builder/Containerfile
grep -qF '/dev/vda2' installer/live/finite/configure-live.d.sh
grep -qF '/dev/vda3' installer/live/finite/configure-live.d.sh
grep -qF 'install -d -m 0755 /usr/local/sbin' installer/live/finite/configure-live.d.sh

grep -qF 'projectbluefin/dakota-iso' lib/installer-application.nix
grep -qF 'projectbluefin/bootc-installer' lib/installer-application.nix
grep -qF 'finite-bluefin-installer-seed-v1' lib/installer-application.nix
grep -qF 'seed_repository="' lib/installer-application.nix
grep -qF 'payload_specific: false' lib/installer-application.nix
grep -qF 'bootc-generic-iso' lib/installer-application.nix
grep -qF -- '--bootc-installer-payload-ref' lib/installer-application.nix
grep -qF -- '--distro' lib/installer-application.nix
grep -qF 'image_builder_distro=' lib/installer-application.nix
grep -qF 'dev.hhd.rechunk.info' lib/installer-application.nix
grep -qF -- '--bootc-ref' lib/installer-application.nix
if grep -qF 'configured_live_image' lib/installer-application.nix; then
	echo 'Installer assembly still creates a derived live configuration image' >&2
	exit 1
fi
if grep -qF 'oci-archive:' lib/installer-application.nix; then
	echo 'Installer assembly still creates an intermediate OCI archive' >&2
	exit 1
fi
if grep -qF 'build-live-squashfs.sh' lib/installer-application.nix; then
	echo 'Installer assembly still calls Dakota squashfs scripts' >&2
	exit 1
fi
grep -qF 'FINITE_INSTALLER_BUILDER_DIGEST' lib/installer-application.nix
grep -qF 'FINITE_IMAGE_BUILDER_DIGEST' lib/installer-application.nix
grep -qF 'root_exec=(run0)' lib/installer-application.nix
grep -qF 'root_exec=(sudo)' lib/installer-application.nix
grep -qF -- '--layers=false' lib/installer-application.nix
grep -qF 'graphDriverName' lib/installer-application.nix
# This intentionally matches the literal shell source.
# shellcheck disable=SC2016
grep -qF 'FROM ${builder_ref} AS initramfs-builder' installer/prepare-bluefin-iso-source
grep -qF 'cosign sign --yes' lib/installer-application.nix
grep -qF 'seed-cache-hit=' lib/installer-application.nix
grep -qF 'seed-published=' lib/installer-application.nix
grep -qF 'schema_version: 4' lib/installer-application.nix
grep -qF 'application: "osbuild/image-builder"' lib/installer-application.nix
grep -qF 'target_bootloader: "grub2"' lib/installer-application.nix
grep -qF 'target_filesystem: "btrfs"' lib/installer-application.nix
grep -qF 'offline: true' lib/installer-application.nix
grep -qF '28732ac11ff8d211ba4b00a0c93ec93b' lib/installer-application.nix

# The reusable seed is keyed by foundation inputs. The published installer is
# intentionally limited to that foundation's generic profile.
source_revision=691e2a4b3b505560a647c9ba7afbca1f5c6fbae7
installer_sha=6d68445965bf03fd628fcc9e856b162939b5f87bf4532f62725cf0e114c7eea7
overlay_a=1111111111111111111111111111111111111111111111111111111111111111
overlay_b=2222222222222222222222222222222222222222222222222222222222222222
digest_a=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
digest_b=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
key_a="$(${installer_build} cache-input "${source_revision}" "${installer_sha}" "${overlay_a}" bluefin "${digest_a}")"
key_same="$(${installer_build} cache-input "${source_revision}" "${installer_sha}" "${overlay_a}" bluefin "${digest_a}")"
key_overlay="$(${installer_build} cache-input "${source_revision}" "${installer_sha}" "${overlay_b}" bluefin "${digest_a}")"
key_foundation="$(${installer_build} cache-input "${source_revision}" "${installer_sha}" "${overlay_a}" bluefin-dx "${digest_a}")"
key_digest="$(${installer_build} cache-input "${source_revision}" "${installer_sha}" "${overlay_a}" bluefin "${digest_b}")"
[[ "${key_a}" =~ ^[0-9a-f]{64}$ ]]
[[ "${key_a}" == "${key_same}" ]]
[[ "${key_a}" != "${key_overlay}" ]]
[[ "${key_a}" != "${key_foundation}" ]]
[[ "${key_a}" != "${key_digest}" ]]

grep -qF "ready_marker='FINITE_INSTALLER_READY=1'" lib/ci-applications/installer-smoke.nix
grep -qF 'root=live:LABEL=FINITE_LIVE' lib/ci-applications/installer-e2e.nix
grep -qF 'finite.installer.autoinstall=1' lib/ci-applications/installer-e2e.nix
grep -qF 'FINITE_INSTALLER_ERROR=' lib/ci-applications/installer-e2e.nix
grep -qF 'FINITE_INSTALLER_COMPLETE=1' lib/ci-applications/installer-e2e.nix
grep -qF 'FINITE_INSTALLED_READY=1' lib/ci-applications/installer-e2e.nix
grep -qF 'OVMF_CODE.fd' lib/ci-applications/installer-e2e.nix
grep -qF 'OVMF_VARS.fd' lib/ci-applications/installer-e2e.nix
grep -qF '(.partitiontable.partitions | length) == 3' lib/ci-applications/installer-e2e.nix
grep -qF 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b' lib/ci-applications/installer-e2e.nix

for phase in \
	'Build installer environment and ISO' \
	'Smoke-test installer ISO bootloader' \
	'Perform unattended installation' \
	'Boot and validate installed system' \
	'Upload installer diagnostics'; do
	grep -qF -- "- name: ${phase}" .github/actions/build-installer/action.yml
done
grep -qF 'seed-digest:' .github/actions/build-installer/action.yml
grep -qF 'seed-cache-hit' .github/actions/build-installer/action.yml
grep -qF 'finite-installer-e2e install' .github/actions/build-installer/action.yml
grep -qF 'finite-installer-e2e boot' .github/actions/build-installer/action.yml
if grep -R -Eqi 'anaconda|kickstart|portable.efi' \
	installer lib/installer-application.nix lib/ci-applications/installer-e2e.nix; then
	echo 'Obsolete Anaconda or portable-EFI implementation remains in the installer path' >&2
	exit 1
fi
