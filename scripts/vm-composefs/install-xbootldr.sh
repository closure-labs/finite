#!/usr/bin/bash
# Fresh installation on the disposable VM disk only, never the workstation.
set -euo pipefail
grep -qw 'finite.vm.install=1' /proc/cmdline
[[ $(cat /sys/class/dmi/id/product_name) == 'Finite Composefs Installer' ]]
[[ -b /dev/vdb && $(blockdev --getsize64 /dev/vdb) == 34359738368 ]]
mkdir -p /inputs
mount -o ro /dev/disk/by-label/FINITEINPUTS /inputs
# The live root is deliberately conventional. Install the very same RPM as the
# candidate before invoking any disk installer, and prove its recorded identity.
python3 - <<'PY'
import hashlib,json
from pathlib import Path
p=Path('/inputs'); r=json.loads((p/'runtime-receipt.json').read_text())
for name,key in [('bootc-runtime.rpm','rpmSha256'),('runtime-source.json','sourceLockSha256')]:
 with (p/name).open('rb') as stream:
  assert hashlib.file_digest(stream,'sha256').hexdigest()==r[key]
PY
rpm -Uvh --oldpackage --replacepkgs /inputs/bootc-runtime.rpm
python3 - <<'PY'
import json,subprocess
from pathlib import Path
pin=json.loads(Path('/inputs/runtime-source.json').read_text())
assert subprocess.check_output(['bootc','--version'],text=True).strip()=='bootc '+pin['version']
assert subprocess.check_output(['rpm','-q','--qf','%{VERSION}-%{RELEASE}','bootc'],text=True)==pin['version']+'-'+pin['rpmRelease']+'.fc44'
print('FINITE_XBOOTLDR_INSTALLER_RUNTIME '+pin['revision'],flush=True)
PY
sfdisk --wipe always /dev/vdb <<'LAYOUT'
label: gpt
unit: sectors

size=600MiB,type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B,name=finite-esp
size=4GiB,type=BC13C2FF-59E6-4262-A352-B275FD6F7172,name=finite-xbootldr
type=4F68BCE3-E8CD-4DB1-96E7-FBCAF984B709,name=finite-root
LAYOUT
udevadm settle
mkfs.fat -F 32 -n FINITEESP /dev/vdb1
mkfs.fat -F 32 -n XBOOTLDR /dev/vdb2
mkfs.ext4 -O verity -L finiteroot /dev/vdb3
mkdir -p /target
mount /dev/vdb3 /target
mkdir -p /target/efi /target/boot
mount /dev/vdb1 /target/efi
mount /dev/vdb2 /target/boot
bootc install to-filesystem --composefs-backend --bootloader systemd \
  --generic-image --skip-finalize --skip-fetch-check \
  --source-imgref oci-archive:/inputs/base.oci.tar \
  --target-transport oci-archive --target-imgref /inputs/base.oci.tar /target
test -n "$(find /target/boot/EFI/Linux -name '*.efi' -type f -print -quit)"
test -n "$(find /target/boot/loader/entries -name '*.conf' -type f -print -quit)"
test ! -d /target/efi/EFI/Linux || test -z "$(find /target/efi/EFI/Linux -name '*.efi' -type f -print -quit)"
test -s /target/efi/EFI/BOOT/BOOTX64.EFI
sync
echo FINITE_VM_INSTALL_COMPLETE
systemctl poweroff
