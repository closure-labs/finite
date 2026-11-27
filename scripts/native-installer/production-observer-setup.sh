#!/usr/bin/env bash
# Install the observer only in a disposable guest's writable /etc.
set -euo pipefail
trap 'echo "FINITE_NATIVE_FRESH_BOOT_FAILED observer setup failed" >&2' ERR
[[ $(systemd-detect-virt --vm) =~ ^(qemu|kvm)$ ]]
[[ $(cat /sys/class/dmi/id/product_serial) == finite-production-install ]]
grep -qw finite.native-installer=1 /proc/cmdline
disk=$(readlink -f /dev/disk/by-id/virtio-FINITEQUALIFICATION)
[[ $disk =~ ^/dev/vd[a-z]$ && $(blockdev --getsize64 "$disk") == 68719476736 ]]
[[ $(blockdev --getro /dev/disk/by-id/virtio-FINITEOBSERVATION) == 1 ]]
[[ $(mokutil --sb-state | head -n 1) == 'SecureBoot enabled' ]]
work=$(mktemp -d /run/finite-production-observer.XXXXXXXX)
mount --mkdir -t ext4 -o ro,noload,nodev,nosuid,noexec /dev/disk/by-id/virtio-FINITEOBSERVATION "$work/inputs"
cryptsetup open --type luks2 "${disk}3" finite-production-observer
mount --mkdir /dev/mapper/finite-production-observer "$work/target"
mount --mkdir -o ro "${disk}1" "$work/target/efi"
mount --mkdir -o ro "${disk}2" "$work/target/boot"
mkdir "$work/deployment"
bootc install mount --sysroot "$work/target" --latest "$work/deployment"
etc="$work/deployment/etc"
install -d -m 0700 "$etc/finite-production-observer"
install -m 0644 "$work/inputs/validation-guest.py" "$work/inputs/serial_records.py" "$etc/finite-production-observer/"
install -d "$etc/systemd/system/multi-user.target.wants"
sed -e '/^Type=oneshot$/a Environment=PYTHONPATH=/usr/libexec/finite' \
    -e 's|/usr/libexec/finite/validation-guest.py|/etc/finite-production-observer/validation-guest.py|' \
    "$work/inputs/validation-guest.service" > "$etc/systemd/system/finite-production-observer.service"
ln -s ../finite-production-observer.service "$etc/systemd/system/multi-user.target.wants/finite-production-observer.service"
chroot "$work/deployment" restorecon -RF /etc/finite-production-observer /etc/systemd/system
umount --recursive "$work/deployment"
umount --recursive "$work/target"
cryptsetup close finite-production-observer
umount "$work/inputs"
sync
printf 'FINITE_PRODUCTION_OBSERVER_READY\n'
