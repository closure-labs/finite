#!/usr/bin/env bash
set -euo pipefail
test -s /usr/share/finite/profile.json
test -s /usr/lib/finite/determinate-nix-seed/receipt.json
test -d /usr/lib/finite/determinate-nix-seed/store
test -s /usr/share/selinux/packages/determinate-nix.pp
test -s /usr/lib/udev/rules.d/70-finite-espanso-input.rules
test -s /usr/share/finite/home-manager-template/customize.nix
test -s /usr/share/finite/home-profile-catalog.json
mapfile -t kernels < <(rpm -q --qf '%{EVR}.%{ARCH}\n' kernel-core)
[[ ${#kernels[@]} == 1 ]]
authselect check
find /usr/libexec/finite/firstboot-rpm-ostree.d -maxdepth 1 -type f -exec chmod 0755 {} +
rm -f /boot/symvers-*.xz
rm -rf /run/dnf /var/lib/rpm-state
# This runs before upstream cleanup. CI additionally lints the assembled image.
bootc container lint
