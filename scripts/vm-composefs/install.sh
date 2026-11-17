#!/usr/bin/bash
# Runs in the disposable installer VM, never on the workstation.
set -euo pipefail
grep -qw 'finite.vm.install=1' /proc/cmdline
[[ $(cat /sys/class/dmi/id/product_name) == 'Finite Composefs Installer' ]]
[[ -b /dev/vdb ]]
case $(blockdev --getsize64 /dev/vdb) in
    34359738368|68719476736) ;;
    *) exit 1 ;;
esac
mkdir -p /inputs
mount -o ro /dev/disk/by-label/FINITEINPUTS /inputs
bootc install to-disk --wipe --filesystem ext4 --bootloader systemd \
  --composefs-backend --skip-fetch-check \
  --source-imgref oci-archive:/inputs/base.oci.tar \
  --target-transport oci-archive --target-imgref /inputs/base.oci.tar /dev/vdb
sync
echo FINITE_VM_INSTALL_COMPLETE
systemctl poweroff
