#!/usr/bin/env bash
set -euo pipefail

aspect_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rootfs="${aspect_root}/rootfs"

test -x "${aspect_root}/apply.sh"
test -x "${aspect_root}/install-determinate-nix.sh"
test -x "${aspect_root}/tests/nix-systemd.sh"
test -x "${aspect_root}/rootfs/usr/libexec/purplefin/require-determinate-nix-version"
test -x "${aspect_root}/packages-bitwarden-cli/install.sh"
test -x "${rootfs}/usr/bin/purplefin-caffeinate"
test -x "${rootfs}/usr/libexec/purplefin/run-firstboot-rpm-ostree"
test -x "${rootfs}/usr/libexec/purplefin/apply-brew-bundle"
test -x "${rootfs}/usr/libexec/purplefin/provision-determinate-nix"
test -x "${rootfs}/usr/libexec/purplefin/install-determinate-nix-selinux-policy"
test -f "${rootfs}/usr/lib/systemd/system/nix.mount"
test -f "${rootfs}/usr/lib/systemd/system/nix-daemon.service"
test -f "${rootfs}/usr/lib/systemd/system/nix-daemon.socket"
test -f "${rootfs}/usr/lib/systemd/system/determinate-nixd.socket"
test -f "${rootfs}/usr/lib/sysusers.d/purplefin-nix.conf"
grep -qF 'What=/var/home/nix' "${rootfs}/usr/lib/systemd/system/nix.mount"
grep -qF 'ExecStart=@/usr/bin/determinate-nixd' "${rootfs}/usr/lib/systemd/system/nix-daemon.service"
grep -qF 'install -d -m 0755 /var/usrlocal/bin' "${aspect_root}/install-determinate-nix.sh"
grep -qF 'dnf5 -y install nix nix-daemon' "${aspect_root}/apply.sh"
grep -qF 'rpm -qf' "${aspect_root}/install-determinate-nix.sh"
grep -qF '/etc/tmpfiles.d/nix-daemon.conf' "${aspect_root}/install-determinate-nix.sh"
grep -qF -- '--no-modify-profile' "${aspect_root}/install-determinate-nix.sh"
grep -qF -- '--nix-build-user-prefix nixbld-' "${aspect_root}/install-determinate-nix.sh"
grep -qF '.minimumRuntimeVersion' "${aspect_root}/install-determinate-nix.sh"
if grep -qF 'install -d -m 0755 /nix' \
	"${aspect_root}/apply.sh" "${aspect_root}/install-determinate-nix.sh"; then
	echo 'Fedora nix-filesystem must own creation of /nix' >&2
	exit 1
fi

grep -qF 'ConditionACPower=true' "${rootfs}/usr/lib/systemd/user/purplefin-caffeinate.service"
grep -qF -- '--what=sleep:handle-lid-switch' "${rootfs}/usr/lib/systemd/user/purplefin-caffeinate.service"
grep -qF '[Flatpak Preinstall org.mozilla.thunderbird]' "${aspect_root}/manifests/flatpaks.preinstall"
grep -qF 'marp-cli' "${aspect_root}/manifests/Brewfile"
grep -qE '^tailscale-stable[[:space:]]+tailscale$' "${aspect_root}/independently-managed-rpms.list"
grep -qF '<action id="com.bitwarden.Bitwarden.unlock">' \
	"${rootfs}/usr/share/polkit-1/actions/com.bitwarden.Bitwarden.policy"
