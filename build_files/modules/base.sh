#!/usr/bin/env bash
set -euo pipefail

# Determinate Nix uses this as a bind-mount target on OSTree systems. Creating
# it during the image build avoids trying to modify the read-only ComposeFS root.
install -d -m 0755 /nix

base_packages=(fuse fuse-libs git micro nm-connection-editor nm-connection-editor-desktop wireguard-tools)
base_qemu_packages=(qemu-block-curl qemu-block-dmg qemu-block-iscsi qemu-block-nfs qemu-block-ssh qemu-img qemu-tools)
base_vm_packages=(podman-machine qemu-system-x86-core)
dnf5 -y install "${base_packages[@]}"
dnf5 -y --setopt=install_weak_deps=False install "${base_qemu_packages[@]}" "${base_vm_packages[@]}"
for package in "${base_packages[@]}" "${base_qemu_packages[@]}" "${base_vm_packages[@]}"; do rpm -q "${package}"; done

# Fedora's podman-machine package supplies the supported gvproxy and
# virtiofsd helper chain. Keep these assertions alongside the explicit QEMU
# provider so an image build fails instead of shipping a partially usable
# `podman machine` command.
for helper in /usr/bin/qemu-system-x86_64 /usr/libexec/podman/gvproxy /usr/libexec/podman/virtiofsd; do
	test -x "${helper}"
done

bash /tmp/purplefin-build/install-bitwarden-cli-rpm.sh
rpm -q purplefin-bitwarden-cli
test "$(rpm -qf --qf '%{NAME}\n' /usr/bin/bw)" = "purplefin-bitwarden-cli"

systemctl enable flatpak-nuke-fedora.service flatpak-preinstall.service purplefin-brew-bundle.service
