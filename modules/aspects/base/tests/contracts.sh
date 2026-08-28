#!/usr/bin/env bash
set -euo pipefail

finite_logo="modules/aspects/base/rootfs/usr/share/finite/finite-logo.png"
test -f "${finite_logo}"
cmp -s "${finite_logo}" \
	modules/aspects/base/rootfs/usr/share/ublue-os/bluefin-logos/bluefin.png
cmp -s \
	modules/aspects/base/rootfs/usr/share/plymouth/themes/spinner/watermark.png \
	modules/aspects/base/rootfs/usr/share/plymouth/themes/spinner/silverblue-watermark.png

aspect_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
module="${aspect_root}/default.nix"
home_module="templates/home-manager/modules/aspects/base/home.nix"
rootfs="${aspect_root}/rootfs"
bitwarden_policy="${rootfs}/usr/share/polkit-1/actions/com.bitwarden.Bitwarden.policy"

test -x "${aspect_root}/apply.sh"
test -x "${aspect_root}/install-determinate-nix.sh"
test -f "${aspect_root}/install-nix-systemd-units.sh"
test -x "${aspect_root}/tests/nix-systemd.sh"
test -x "${aspect_root}/rootfs/usr/libexec/finite/require-determinate-nix-version"
test -x "${rootfs}/usr/bin/finite-caffeinate"
test -x "${rootfs}/usr/libexec/finite/run-firstboot-rpm-ostree"
test -x "${rootfs}/usr/libexec/finite/provision-determinate-nix"
test -x "${rootfs}/usr/libexec/finite/install-determinate-nix-selinux-policy"
test -x "${rootfs}/usr/libexec/finite/home-first-login"
bash -n "${rootfs}/usr/libexec/finite/home-first-login"
test -f "${rootfs}/usr/lib/systemd/system/nix.mount"
grep -qF 'd /var/lib/cloud 0755 root root - -' \
	"${rootfs}/usr/lib/tmpfiles.d/finite-cloud-init.conf"
test -f "${rootfs}/usr/lib/systemd/system/nix-daemon.service"
test -f "${rootfs}/usr/lib/systemd/system/nix-daemon.socket"
test -f "${rootfs}/usr/lib/systemd/system/determinate-nixd.socket"
test -f "${rootfs}/usr/lib/systemd/system/finite-nix-socket-cleanup.service"
test -f "${rootfs}/usr/lib/sysusers.d/finite-nix.conf"
test -f "${bitwarden_policy}"
grep -qF '<action id="com.bitwarden.Bitwarden.unlock">' "${bitwarden_policy}"
grep -qF '<allow_active>auth_self</allow_active>' "${bitwarden_policy}"
grep -qF 'What=/var/home/nix' "${rootfs}/usr/lib/systemd/system/nix.mount"
grep -qF 'ExecStart=@/usr/bin/determinate-nixd' "${rootfs}/usr/lib/systemd/system/nix-daemon.service"
grep -qF 'Requires=finite-nix-socket-cleanup.service' \
	"${rootfs}/usr/lib/systemd/system/nix-daemon.socket"
grep -qF 'RemoveOnStop=true' "${rootfs}/usr/lib/systemd/system/nix-daemon.socket"
grep -qF '/nix/var/nix/daemon-socket/socket' \
	"${rootfs}/usr/lib/systemd/system/finite-nix-socket-cleanup.service"
grep -qF 'install -d -m 0755 /var/usrlocal/bin' "${aspect_root}/install-determinate-nix.sh"
grep -qF 'dnf5 -y install cloud-init jq nix nix-daemon yq zenity' "${aspect_root}/apply.sh"
dnf_line="$(grep -nF 'dnf5 -y install cloud-init jq nix nix-daemon yq zenity' "${aspect_root}/apply.sh" | cut -d: -f1)"
rootfs_overlay="cp -a \"\${base_root}/rootfs/.\" /"
overlay_line="$(grep -nF "${rootfs_overlay}" "${aspect_root}/apply.sh" | cut -d: -f1)"
if ((overlay_line <= dnf_line)); then
	echo 'Finite rootfs must overlay Fedora packages after package installation' >&2
	exit 1
fi
grep -qF 'rm -rf -- /run/cloud-init' "${aspect_root}/apply.sh"
grep -qF 'rpm -qf' "${aspect_root}/install-determinate-nix.sh"
grep -qF 'native_nix_env=/usr/bin/nix-env' "${aspect_root}/install-determinate-nix.sh"
grep -qF 'generated/nix.fc' "${aspect_root}/install-determinate-nix.sh"
grep -qF 'semanage fcontext -a -e /nix /var/home/nix' \
	"${rootfs}/usr/libexec/finite/install-determinate-nix-selinux-policy"
grep -qF 'semanage fcontext -m -e /nix /var/home/nix' \
	"${rootfs}/usr/libexec/finite/install-determinate-nix-selinux-policy"
grep -qF '/etc/tmpfiles.d/nix-daemon.conf' "${aspect_root}/install-determinate-nix.sh"
grep -qF 'install -m 0644 /dev/null /etc/tmpfiles.d/nix-daemon.conf' \
	"${aspect_root}/install-determinate-nix.sh"
grep -qF 'install -m 0644 /dev/null /etc/tmpfiles.d/nix-filesystem.conf' \
	"${aspect_root}/install-determinate-nix.sh"
grep -qF -- '--no-modify-profile' "${aspect_root}/install-determinate-nix.sh"
grep -qF -- '--nix-build-user-prefix nixbld-' "${aspect_root}/install-determinate-nix.sh"
grep -qF '.minimumRuntimeVersion' "${aspect_root}/install-determinate-nix.sh"
if grep -qF 'install-nix-systemd-units.sh' "${aspect_root}/install-determinate-nix.sh"; then
	echo 'Nix systemd activation must be normalized after all build steps' >&2
	exit 1
fi
grep -qF 'install-nix-systemd-units.sh' "${aspect_root}/apply.sh"
cloud_enable_line="$(grep -nF 'systemctl enable cloud-init.target' "${aspect_root}/apply.sh" | cut -d: -f1)"
nix_units_line="$(grep -nF 'install-nix-systemd-units.sh' "${aspect_root}/apply.sh" | cut -d: -f1)"
if ((nix_units_line <= cloud_enable_line)); then
	echo 'Nix systemd activation must be the final image normalization step' >&2
	exit 1
fi
grep -qF 'multi-user.target.wants' "${aspect_root}/install-nix-systemd-units.sh"
grep -qF "remove_activation_link \"\${root}\" nix-daemon.socket sockets.target.wants" \
	"${aspect_root}/install-nix-systemd-units.sh"
grep -qF "remove_activation_link \"\${root}\" determinate-nixd.socket sockets.target.wants" \
	"${aspect_root}/install-nix-systemd-units.sh"
grep -qF "remove_activation_link \"\${root}\" nix-daemon.service multi-user.target.wants" \
	"${aspect_root}/install-nix-systemd-units.sh"
grep -qF 'install_vendor_want nix-daemon.socket multi-user.target.wants' \
	"${aspect_root}/install-nix-systemd-units.sh"
grep -qF 'install_vendor_want determinate-nixd.socket multi-user.target.wants' \
	"${aspect_root}/install-nix-systemd-units.sh"
if grep -qF 'install -d -m 0755 /nix' \
	"${aspect_root}/apply.sh" "${aspect_root}/install-determinate-nix.sh"; then
	echo 'Fedora nix-filesystem must own creation of /nix' >&2
	exit 1
fi

grep -qF 'ConditionACPower=true' "${rootfs}/usr/lib/systemd/user/finite-caffeinate.service"
grep -qF -- '--what=sleep:handle-lid-switch' "${rootfs}/usr/lib/systemd/user/finite-caffeinate.service"
grep -qF 'datasource_list: [NoCloud, None]' "${rootfs}/etc/cloud/cloud.cfg.d/90-finite-nocloud.cfg"
grep -qF "mode: 'off'" "${rootfs}/etc/cloud/cloud.cfg.d/90-finite-nocloud.cfg"
grep -qF 'resize_rootfs: false' "${rootfs}/etc/cloud/cloud.cfg.d/90-finite-nocloud.cfg"
test ! -e "${aspect_root}/manifests/Brewfile"
test ! -e "${aspect_root}/independently-managed-rpms.list"
test ! -e "${aspect_root}/packages-bitwarden-cli"
grep -qF 'nh.enable = true' "${home_module}"
if grep -qF 'home-manager.enable = true' "${home_module}"; then
	echo 'The standalone Home Manager CLI must not shadow nh' >&2
	exit 1
fi
test -f "${rootfs}/usr/lib/systemd/user/finite-home-first-login.service"
test -L "${rootfs}/etc/systemd/user/graphical-session.target.wants/finite-home-first-login.service"
test -x "${rootfs}/usr/libexec/finite/home-init"
bash -n "${rootfs}/usr/libexec/finite/home-init"
grep -qF 'FINITE_NIX_WAIT_SECONDS:-120' \
	"${rootfs}/usr/libexec/finite/home-first-login"
grep -qF 'systemctl is-active --quiet nix-daemon.socket determinate-nixd.socket' \
	"${rootfs}/usr/libexec/finite/home-first-login"
if grep -qF 'finite-home' "${module}"; then
	echo 'The removed finite-home compatibility alias remains' >&2
	exit 1
fi
