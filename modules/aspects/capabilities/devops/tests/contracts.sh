#!/usr/bin/env bash
set -euo pipefail

aspect_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rootfs="${aspect_root}/rootfs"

test -x "${aspect_root}/apply.sh"
for helper in configure-zsh-defaults install-ghostty-defaults install-zsh-defaults; do
	test -x "${rootfs}/usr/libexec/purplefin/${helper}"
done
for file in .zshenv .zshrc aliases.zsh bindings.zsh fzf.zsh plugins.zsh prompt.zsh starship.toml LICENSE; do
	test -f "${rootfs}/usr/share/purplefin/zsh/${file}"
done
grep -qxF 'command = /usr/bin/zsh' "${rootfs}/etc/skel/.config/ghostty/config.ghostty"
grep -qxF 'WantedBy=default.target' "${rootfs}/usr/lib/systemd/user/purplefin-zsh-defaults.service"
grep -qF '[Flatpak Preinstall com.vscodium.codium]' "${aspect_root}/manifests/flatpaks.preinstall"
grep -qxF openbao "${aspect_root}/manifests/rpms.list"
