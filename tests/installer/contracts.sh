#!/usr/bin/env bash
set -euo pipefail

installer_build="${1:?usage: contracts.sh INSTALLER_BUILD}"

jq -e '
  .schema == 3 and
  .iso_source.owner == "projectbluefin" and
  .iso_source.repository == "dakota-iso" and
  (.iso_source.revision | test("^[0-9a-f]{40}$")) and
  (.iso_source.hash | startswith("sha256-")) and
  (.installer.version | test("^[0-9]+\\.[0-9]+\\.[0-9]+$")) and
  (.installer.url | startswith("https://github.com/projectbluefin/bootc-installer/releases/download/")) and
  (.installer.sha256 | test("^[0-9a-f]{64}$")) and
  .live_image.image == "ghcr.io/projectbluefin/dakota" and
  .live_image.tag == "stable" and
  .live_image.architecture == "amd64" and
  (.live_image.digest | test("^sha256:[0-9a-f]{64}$")) and
  .live_image.cosign.issuer == "https://token.actions.githubusercontent.com" and
  (.live_image.cosign.identity | contains("projectbluefin/dakota/.github/workflows/publish.yml")) and
  .builder.image == "docker.io/library/debian" and
  .builder.tag == "bookworm" and
  .builder.architecture == "amd64" and
  (.builder.digest | test("^sha256:[0-9a-f]{64}$"))
' sources/dakota-installer.json >/dev/null

test -x installer/prepare-dakota-iso-source
test -x installer/live/finite/configure-live.d.sh
test ! -e installer/prepare-bluefin-iso-source
test ! -e installer/live/finite/iso.yaml
test ! -e installer/live/finite/bootc-install-defaults.toml
for file in images.json recipe.json ci-autoinstall.json; do
	jq -e . "installer/live/finite/${file}" >/dev/null
done
grep -qFx 'grub' installer/live/finite/bootloader
grep -qFx 'false' installer/live/finite/composefs
grep -qF '@@PAYLOAD_REFERENCE@@' installer/live/finite/recipe.json
grep -qF '@@UPDATE_REFERENCE@@' installer/live/finite/recipe.json
grep -qF '@@PAYLOAD_REFERENCE@@' installer/live/finite/ci-autoinstall.json
grep -qF '"targetImgref": "@@UPDATE_REFERENCE@@"' installer/live/finite/ci-autoinstall.json
grep -qF '"hostname": "finite"' installer/live/finite/recipe.json
grep -qF '"hostname": "finite"' installer/live/finite/ci-autoinstall.json
grep -qF '"disk": "/dev/vda"' installer/live/finite/ci-autoinstall.json
grep -qF '"filesystem": "btrfs"' installer/live/finite/ci-autoinstall.json
grep -qF '"log_file": "/home/liveuser/.cache/finite-installer/finite-installer.log"' \
	installer/live/finite/recipe.json

live_hook=installer/live/finite/configure-live.d.sh
grep -qF 'FINITE_INSTALLER_READY=1' "${live_hook}"
grep -qF 'FINITE_INSTALLER_COMPLETE=1' "${live_hook}"
grep -qF 'FINITE_INSTALLER_DEPLOYMENT_CHECKSUM=%s' "${live_hook}"
grep -qF 'FINITE_INSTALLED_READY=1' "${live_hook}"
grep -qF 'finite.installer.autoinstall=1' "${live_hook}"
grep -qF 'finite-netinstall-mode' "${live_hook}"
grep -qF 'rm -f ' "${live_hook}"
grep -qF '/etc/bootc-installer/live-iso-mode' "${live_hook}"
grep -qF 'ConditionPathExists=/etc/bootc-installer/finite-netinstall-mode' "${live_hook}"
grep -qF 'AutomaticLogin=liveuser' "${live_hook}"
grep -qF 'DefaultSession=gnome.desktop' "${live_hook}"
grep -qF 'FINITE_INSTALLER_ERROR=liveuser-graphical-session-timeout' "${live_hook}"
grep -qF "sudo --user \"\${live_user}\" --" "${live_hook}"
grep -qF "\"\${user_systemctl[@]}\" is-active --quiet finite-installer.service" \
	"${live_hook}"
grep -qF "activation_marker='Installer::Main INFO: do_activate called'" "${live_hook}"
grep -qF 'finite-installer-apply-target' "${live_hook}"
grep -qF 'finite-installer-target-config.service' "${live_hook}"
grep -qF 'findmnt --raw --noheadings --types iso9660' "${live_hook}"
grep -qF 'payload_reference' "${live_hook}"
grep -qF "fisherman validate \"\${validation_recipe}\"" "${live_hook}"
grep -qF "report_startup_error 'installer-preflight-failed'" "${live_hook}"
grep -qF 'required_executables=(' "${live_hook}"
grep -qF $'\tchroot' "${live_hook}"
grep -qF 'mkfs.btrfs' "${live_hook}"
grep -qF $'\tpodman' "${live_hook}"
grep -qF "getent ahosts \"\${registry}\"" "${live_hook}"
grep -qF "skopeo inspect --retry-times 3 \"docker://\${payload_reference}\"" "${live_hook}"
grep -qF 'FINITE_INSTALLER_MIN_SCRATCH_BYTES' "${live_hook}"
grep -qF 'FINITE_INSTALLER_PREFLIGHT=ok' "${live_hook}"
grep -qF "mkfs.ext4 -F \"\${scratch}\"" "${live_hook}"
grep -qF "flatpak kill \"\${app_id}\"" "${live_hook}"
grep -qF 'Installation complete!' "${live_hook}"
grep -qF 'Installation failed!' "${live_hook}"
grep -qF 'fisherman-output.log' "${live_hook}"
grep -qF 'BOOTC_INSTALLER_DEBUG=1' "${live_hook}"
grep -qF 'finite-installer.log' "${live_hook}"
grep -qF 'autoinstall_sandbox=' "${live_hook}"
grep -qF '.cache/finite-installer/ci-autoinstall.json' "${live_hook}"
grep -qF 'FINITE_DIAGNOSTIC_BEGIN=' "${live_hook}"
grep -qF 'lsblk --fs --output-all' "${live_hook}"
grep -qF 'findmnt --real --output-all' "${live_hook}"
grep -qF 'sudo podman system df' "${live_hook}"
grep -qF 'journalctl --boot --no-pager --lines 500' "${live_hook}"
grep -qF '/dev/vda2' "${live_hook}"
grep -qF '/dev/vda3' "${live_hook}"
grep -qF "find \"\${system_root}/ostree/deploy\"" "${live_hook}"
grep -qF -- "-path \"\${system_root}/ostree/deploy/*/deploy/*\"" "${live_hook}"
grep -qF 'Expected exactly one installed OSTree deployment' "${live_hook}"
grep -qF "[[ \"\${deployment_name}\" =~ ^[0-9a-f]{64}\\.[0-9]+\$ ]]" "${live_hook}"
if grep -qF -- "-name '*.0'" "${live_hook}"; then
	echo 'Installer deployment discovery can still select an OSTree backing directory' >&2
	exit 1
fi
grep -qF "systemd_root=\"\${deployment_root}/etc/systemd/system\"" "${live_hook}"
grep -qF 'Installed SELinux setfiles executable is missing' "${live_hook}"
grep -qF "file_contexts_tmp=\$(mktemp \"\${contexts_root}/finite-ci-file-contexts.XXXXXX\")" \
	"${live_hook}"
grep -qF 'restorecon intentionally' "${live_hook}"
grep -qF "chroot \"\${deployment_root}\" /usr/bin/setfiles -C -F -m -v" \
	"${live_hook}"
grep -qF -- "-c \"\${policy_binary_chroot}\"" "${live_hook}"
grep -qF "mount --bind \"\${var_root}\" \"\${deployment_root}/var\"" \
	"${live_hook}"
grep -qF 'WantedBy=cloud-init.target' "${live_hook}"
grep -qF 'cloud-init.target.wants/finite-ci-installed-ready.service' "${live_hook}"
grep -qF 'ExecStart=/usr/bin/bash /etc/systemd/system/finite-ci-installed-ready' \
	"${live_hook}"
grep -qF 'FINITE_INSTALLED_ERROR=status=%s line=%s' "${live_hook}"
grep -qF 'FINITE_INSTALLED_DIAGNOSTICS_BEGIN=1' "${live_hook}"
grep -qF 'FINITE_SYSROOT_FSTYPE=%s' "${live_hook}"
grep -qF 'FINITE_SELINUX_MODE=%s' "${live_hook}"
grep -qF 'FINITE_CLOUD_INIT_STATUS=%s' "${live_hook}"
grep -qF 'FINITE_NIX_VERSION=%s' "${live_hook}"
grep -qF 'FINITE_USER_HOME=%s' "${live_hook}"
# The literal shell expression is the contract under test.
# shellcheck disable=SC2016
grep -qF '[[ "${finite_home}" == /var/home/finiteci ]]' "${live_hook}"
grep -qF 'store info --store daemon' "${live_hook}"
grep -qF '((cloud_status_exit == 0 || cloud_status_exit == 2))' "${live_hook}"
grep -qF 'matchpathcon -V /etc/passwd /etc/group /var/home/finiteci' "${live_hook}"
grep -qF 'cloud-final.service' "${live_hook}"
grep -qF 'nix-daemon.service' "${live_hook}"
grep -qF '/usr/bin/jq -c .' "${live_hook}"

prepare=installer/prepare-dakota-iso-source
grep -qF 'ARG LIVE_ROOT=dakota' "${prepare}"
grep -qF 'live_root_arg_count' "${prepare}"
grep -qF "FROM ghcr.io/\${REGISTRY}/\${LIVE_ROOT}:\${TAG}" "${prepare}"
grep -qF 'SUPERISO_COMPRESSION:-lz4' "${prepare}"
grep -qF 'SFS_ARGS=(-comp lz4)' "${prepare}"
if grep -qF -- '-Xhc' "${prepare}"; then
	echo 'Dakota source preparation still requests LZ4 high-compression mode' >&2
	exit 1
fi
grep -qF 'btrfs-progs' "${prepare}"
grep -qF '/usr/libexec/finite-btrfs/mkfs.btrfs' "${prepare}"
grep -qF '/usr/libexec/finite-btrfs/ld-linux' "${prepare}"
grep -qF '/usr/lib/finite-btrfs/' "${prepare}"
grep -qF 'source=/,target=/run/finite-builder,ro' "${prepare}"
grep -qF 'FINITE_TARGET_CONFIG must name the resolved target JSON' "${prepare}"
grep -qF 'prepare-dakota-iso-source failed: stage=' "${prepare}"
grep -qF 'installer.flatpak' "${prepare}"
grep -qF '@@PAYLOAD_REFERENCE@@' "${prepare}"
grep -qF '@@UPDATE_REFERENCE@@' "${prepare}"

application=lib/installer-application.nix
grep -qF 'projectbluefin/dakota-iso' "${application}"
grep -qF 'projectbluefin/bootc-installer' "${application}"
grep -qF 'finite-dakota-netinstaller-seed-v2' "${application}"
grep -qF 'FINITE_DAKOTA_LIVE_DIGEST' "${application}"
grep -qF 'dakota_live_build_ref=' "${application}"
grep -qF 'cosign verify' "${application}"
grep -qF 'cosign sign --yes' "${application}"
grep -qF 'oras pull' "${application}"
grep -qF 'oras push' "${application}"
grep -qF 'application/vnd.finite.installer.seed.v1' "${application}"
grep -qF 'FINITE_INSTALLER_SEED_CACHE_DIR' "${application}"
grep -qF 'modules/aspects/base/rootfs/usr/share/finite/finite-logo.png' "${application}"
grep -qF 'seed_cache_source=github-actions' "${application}"
grep -qF 'build-live-squashfs.sh' "${application}"
grep -qF 'live/src/build-iso.sh' "${application}"
grep -qF 'SUPERISO_COMPRESSION=lz4' "${application}"
grep -qF 'diagnostics/source-prepare.log' "${application}"
grep -qF 'root_exec=(sudo)' "${application}"
grep -qF -- '--layers=false' "${application}"
grep -qF 'schema_version: 6' "${application}"
grep -qF 'boot: "systemd-boot"' "${application}"
grep -qF 'compression: "lz4"' "${application}"
grep -qF 'target_bootloader: "grub2"' "${application}"
grep -qF 'target_filesystem: "btrfs"' "${application}"
grep -qF 'network_required: true' "${application}"
grep -qF 'offline: false' "${application}"
grep -qF 'embedded: false' "${application}"
grep -qF 'FINITE_TARGET_CONFIG="' "${application}"
grep -qF '/finite/target.json' "${application}"
if grep -Eq 'osbuild/image-builder|bootc-generic-iso|--bootc-installer-payload-ref|oci-archive:' "${application}"; then
	echo 'Legacy Image Builder or embedded-payload path remains in the netinstaller' >&2
	exit 1
fi
if grep -Eq 'target-layer|configure-target\.py|live_image=' "${application}"; then
	echo 'Installer assembly still builds a payload-specific live container' >&2
	exit 1
fi
if grep -qF 'root_exec=(run0)' "${application}"; then
	echo 'Installer application still selects the session-only run0 helper' >&2
	exit 1
fi

source_revision=691e2a4b3b505560a647c9ba7afbca1f5c6fbae7
installer_sha=6d68445965bf03fd628fcc9e856b162939b5f87bf4532f62725cf0e114c7eea7
overlay_a=1111111111111111111111111111111111111111111111111111111111111111
overlay_b=2222222222222222222222222222222222222222222222222222222222222222
digest_a=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
digest_b=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
key_a="$(${installer_build} cache-input "${source_revision}" "${installer_sha}" "${overlay_a}" "${digest_a}")"
key_same="$(${installer_build} cache-input "${source_revision}" "${installer_sha}" "${overlay_a}" "${digest_a}")"
key_overlay="$(${installer_build} cache-input "${source_revision}" "${installer_sha}" "${overlay_b}" "${digest_a}")"
key_live="$(${installer_build} cache-input "${source_revision}" "${installer_sha}" "${overlay_a}" "${digest_b}")"
[[ "${key_a}" =~ ^[0-9a-f]{64}$ ]]
[[ "${key_a}" == "${key_same}" ]]
[[ "${key_a}" != "${key_overlay}" ]]
[[ "${key_a}" != "${key_live}" ]]

grep -qF "ready_marker='FINITE_INSTALLER_READY=1'" lib/ci-applications/installer-smoke.nix
grep -qF 'root=live:LABEL=FINITE_LIVE' lib/ci-applications/installer-e2e.nix
grep -qF 'finite.installer.autoinstall=1' lib/ci-applications/installer-e2e.nix
grep -qF 'FINITE_INSTALLER_COMPLETE=1' lib/ci-applications/installer-e2e.nix
grep -qF 'FINITE_INSTALLER_SOURCE_DIGEST=' "${live_hook}"
grep -qF 'expected-source-digest' lib/ci-applications/installer-e2e.nix
grep -qF 'expected-ostree-checksum' lib/ci-applications/installer-e2e.nix
grep -qF "value=\"''\${value//\$'\\r'/}\"" lib/ci-applications/installer-e2e.nix
grep -qF 'FINITE_INSTALLED_READY=1' lib/ci-applications/installer-e2e.nix
grep -qF 'FINITE_INSTALLED_ERROR=' lib/ci-applications/installer-e2e.nix
grep -qF 'Installer source digest mismatch:' lib/ci-applications/installer-e2e.nix
grep -qF 'Installed OSTree deployment mismatch:' lib/ci-applications/installer-e2e.nix
grep -qF ".status.booted.ostree.checksum" lib/ci-applications/installer-e2e.nix
grep -qF 'FINITE_SYSROOT_FSTYPE' "${live_hook}"
grep -qF 'FINITE_GRUB2_READY' "${live_hook}"
grep -qF 'Installed hostname mismatch:' lib/ci-applications/installer-e2e.nix
grep -qF 'Installed sysroot filesystem mismatch:' lib/ci-applications/installer-e2e.nix
grep -qF 'Installed Fedora version mismatch:' lib/ci-applications/installer-e2e.nix
grep -qF 'Installed GRUB2 configuration is missing' lib/ci-applications/installer-e2e.nix
grep -qF 'extract_guest_diagnostics()' lib/ci-applications/installer-e2e.nix
grep -qF 'OVMF_CODE.fd' lib/ci-applications/installer-e2e.nix
grep -qF 'FINITE_INSTALLER_SMOKE_MEMORY_MB:-11264' \
	lib/ci-applications/installer-smoke.nix
grep -qF '(.partitiontable.partitions | length) == 3' lib/ci-applications/installer-e2e.nix

for phase in \
	'Build installer environment and ISO' \
	'Smoke-test installer ISO bootloader' \
	'Perform unattended installation' \
	'Boot and validate installed system' \
	'Upload installer diagnostics'; do
	grep -qF -- "- name: ${phase}" .github/actions/build-installer/action.yml
done
grep -qF 'seed-cache-hit' .github/actions/build-installer/action.yml
grep -qF 'Restore exact installer seed artifacts' .github/actions/build-installer/action.yml
grep -qF "finite-installer-seed-v2-\${{ runner.os }}-\${{ steps.seed-key.outputs.key }}" \
	.github/actions/build-installer/action.yml
grep -qF 'actions/cache/restore@caa296126883cff596d87d8935842f9db880ef25' \
	.github/actions/build-installer/action.yml
grep -qF 'actions/cache/save@caa296126883cff596d87d8935842f9db880ef25' \
	.github/actions/build-installer/action.yml
grep -qF "if: steps.seed-actions-cache.outputs.cache-hit != 'true'" \
	.github/actions/build-installer/action.yml
# The GitHub expression is intentionally matched literally.
# shellcheck disable=SC2016
grep -qF 'key: ${{ steps.seed-actions-cache.outputs.cache-primary-key }}' \
	.github/actions/build-installer/action.yml
grep -qF 'finite-installer-e2e install' .github/actions/build-installer/action.yml
grep -qF 'finite-installer-e2e boot' .github/actions/build-installer/action.yml
# The GitHub expression is intentionally matched literally.
# shellcheck disable=SC2016
grep -qF 'EXPECTED_SOURCE_DIGEST: ${{ steps.installer.outputs.payload-digest }}' \
	.github/actions/build-installer/action.yml
grep -qF 'payload-ostree-checksum:' .github/actions/build-installer/action.yml
if grep -R -Eqi 'anaconda|kickstart|portable.efi' \
	installer/live installer/prepare-dakota-iso-source lib/installer-application.nix; then
	echo 'Obsolete Anaconda or portable-EFI implementation remains in the installer path' >&2
	exit 1
fi
