#!/usr/bin/env bash
set -euo pipefail

build_root="${PURPLEFIN_BUILD_ROOT:-/tmp/purplefin-build}"
base_root="${build_root}/modules/aspects/base"

cp -a "${base_root}/rootfs/." /

# Fedora owns the host filesystem and account contracts used to bootstrap Nix.
# Pin the otherwise-dynamic build identities before installing the packages so
# Determinate Nix Installer can migrate the upstream installation in place.
systemd-sysusers /usr/lib/sysusers.d/purplefin-nix.conf
dnf5 -y install cloud-init nix nix-daemon
rpm -q cloud-init nix nix-daemon nix-filesystem nix-system
# Package scriptlets may populate the build container's transient /run tree.
# Cloud-init recreates this state at boot; it must not enter the bootc commit.
rm -rf -- /run/cloud-init
install -m 0644 /usr/lib/sysusers.d/purplefin-nix.conf /usr/lib/sysusers.d/nix.conf
rm /usr/lib/sysusers.d/purplefin-nix.conf

# Bake the complete Determinate Nix payload into the immutable image. The
# Fedora nix-filesystem package supplies /nix; at boot systemd seeds persistent
# /var state and bind-mounts it on that mountpoint.
bash "${base_root}/install-determinate-nix.sh"
systemctl enable cloud-init.target
