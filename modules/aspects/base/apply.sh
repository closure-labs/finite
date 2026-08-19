#!/usr/bin/env bash
set -euo pipefail

build_root="${PURPLEFIN_BUILD_ROOT:-/tmp/purplefin-build}"
base_root="${build_root}/modules/aspects/base"

cp -a "${base_root}/rootfs/." /
install -D -m 0644 "${base_root}/manifests/Brewfile" \
	/usr/share/purplefin/manifests/Brewfile
install -D -m 0644 "${base_root}/manifests/flatpaks.preinstall" \
	/usr/share/flatpak/preinstall.d/purplefin.preinstall

# Fedora owns the host filesystem and account contracts used to bootstrap Nix.
# Pin the otherwise-dynamic build identities before installing the packages so
# Determinate Nix Installer can migrate the upstream installation in place.
systemd-sysusers /usr/lib/sysusers.d/purplefin-nix.conf
dnf5 -y install nix nix-daemon
rpm -q nix nix-daemon nix-filesystem nix-system
install -m 0644 /usr/lib/sysusers.d/purplefin-nix.conf /usr/lib/sysusers.d/nix.conf
rm /usr/lib/sysusers.d/purplefin-nix.conf

# Bake the complete Determinate Nix payload into the immutable image. The
# Fedora nix-filesystem package supplies /nix; at boot systemd seeds persistent
# /var state and bind-mounts it on that mountpoint.
bash "${base_root}/install-determinate-nix.sh"

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

bash "${base_root}/packages-bitwarden-cli/install.sh"
rpm -q purplefin-bitwarden-cli
test "$(rpm -qf --qf '%{NAME}\n' /usr/bin/bw)" = "purplefin-bitwarden-cli"

systemctl enable flatpak-nuke-fedora.service flatpak-preinstall.service purplefin-brew-bundle.service
