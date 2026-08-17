#!/usr/bin/env bash
set -euo pipefail

aspect_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rootfs="${aspect_root}/rootfs"

test -x "${aspect_root}/apply.sh"
test -x "${aspect_root}/packages-bitwarden-cli/install.sh"
test -x "${rootfs}/usr/bin/purplefin-caffeinate"
test -x "${rootfs}/usr/libexec/purplefin/run-firstboot-rpm-ostree"
test -x "${rootfs}/usr/libexec/purplefin/apply-brew-bundle"

grep -qF 'ConditionACPower=true' "${rootfs}/usr/lib/systemd/user/purplefin-caffeinate.service"
grep -qF -- '--what=sleep:handle-lid-switch' "${rootfs}/usr/lib/systemd/user/purplefin-caffeinate.service"
grep -qF '[Flatpak Preinstall org.mozilla.thunderbird]' "${aspect_root}/manifests/flatpaks.preinstall"
grep -qF 'marp-cli' "${aspect_root}/manifests/Brewfile"
grep -qE '^tailscale-stable[[:space:]]+tailscale$' "${aspect_root}/independently-managed-rpms.list"
grep -qF '<action id="com.bitwarden.Bitwarden.unlock">' \
	"${rootfs}/usr/share/polkit-1/actions/com.bitwarden.Bitwarden.policy"
