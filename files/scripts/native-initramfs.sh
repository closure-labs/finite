#!/usr/bin/env bash
# Build a native initramfs while preserving inherited kernel/module bytes.
set -euo pipefail
mapfile -t kernels < <(rpm -q --qf '%{VERSION}-%{RELEASE}.%{ARCH}\n' kernel-core)
[[ ${#kernels[@]} == 1 ]]
install -d /usr/lib/composefs /usr/lib/bootc/kargs.d /usr/lib/bootc/install/systemd-boot \
  /usr/lib/finite/efi /kernel /boot/EFI/Linux /efi
printf '%s\n' '# Persistent /etc and /var use the native bootc defaults.' > /usr/lib/composefs/setup-root-conf.toml
rm -f /usr/lib/ostree/prepare-root.conf /etc/ostree/prepare-root.conf
printf '%s\n' 'kargs = ["rw"]' > /usr/lib/bootc/kargs.d/00-finite-native.toml
printf '%s\n' 'timeout 5' 'editor no' 'secure-boot-enroll off' > /usr/lib/bootc/install/systemd-boot/loader.conf
dracut --force --no-hostonly --omit ostree --add 'bootc crypt systemd-cryptsetup fido2' \
  "/usr/lib/modules/${kernels[0]}/initramfs.img" "${kernels[0]}"
bash /usr/libexec/finite/check-initramfs "${kernels[0]}" /usr/lib/modules native
