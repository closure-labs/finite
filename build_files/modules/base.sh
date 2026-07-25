#!/usr/bin/env bash
set -euo pipefail

# Determinate Nix uses this as a bind-mount target on OSTree systems. Creating
# it during the image build avoids trying to modify the read-only ComposeFS root.
install -d -m 0755 /nix

echo ":: Removing inherited Tailscale"
systemctl disable tailscaled.service >/dev/null 2>&1 || true
rm -f /etc/yum.repos.d/tailscale.repo /usr/share/ublue-os/privileged-setup.hooks.d/10-tailscale.sh /usr/share/fish/completions/tailscale.fish /etc/default/tailscaled
if [[ -f /etc/dnf/repos.override.d/99-config_manager.repo ]]; then
	sed -i '/^\[tailscale-stable\]$/,+1d' /etc/dnf/repos.override.d/99-config_manager.repo
fi
if rpm -q tailscale >/dev/null 2>&1; then
	dnf5 -y remove --no-autoremove tailscale
fi

base_packages=(fuse fuse-libs git micro nm-connection-editor nm-connection-editor-desktop wireguard-tools)
base_qemu_packages=(qemu-block-curl qemu-block-dmg qemu-block-iscsi qemu-block-nfs qemu-block-ssh qemu-img qemu-tools)
dnf5 -y install "${base_packages[@]}"
dnf5 -y --setopt=install_weak_deps=False install "${base_qemu_packages[@]}"
for package in "${base_packages[@]}" "${base_qemu_packages[@]}"; do rpm -q "${package}"; done

bash /tmp/purplefin-build/install-bitwarden-cli-rpm.sh
rpm -q purplefin-bitwarden-cli
test "$(rpm -qf --qf '%{NAME}\n' /usr/bin/bw)" = "purplefin-bitwarden-cli"

systemctl enable flatpak-nuke-fedora.service flatpak-preinstall.service purplefin-brew-bundle.service
