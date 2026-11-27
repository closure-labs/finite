#!/usr/bin/bash
# A negative compatibility probe on a loop disk inside the disposable VM only.
set -euo pipefail
[[ $EUID == 0 && -f /usr/share/finite-vm/revision ]]
case $(systemd-detect-virt --vm) in qemu|kvm) ;; *) exit 2 ;; esac
work=$(mktemp -d /var/tmp/finite-xbootldr.XXXXXXXX)
device=
cleanup() {
  umount -R "$work/target" 2>/dev/null || true
  umount "$work/inputs" 2>/dev/null || true
  if [[ -n $device ]]; then losetup -d "$device"; fi
  rm -rf -- "$work"
}
trap cleanup EXIT
truncate -s 16G "$work/disk.raw"
device=$(losetup --find --show --partscan "$work/disk.raw")
[[ $device =~ ^/dev/loop[0-9]+$ ]]
sfdisk "$device" >"$work/partition.log" 2>&1 <<'LAYOUT'
label: gpt
unit: sectors

size=600MiB,type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B,name=probe-esp
size=4GiB,type=BC13C2FF-59E6-4262-A352-B275FD6F7172,name=probe-xbootldr
type=4F68BCE3-E8CD-4DB1-96E7-FBCAF984B709,name=probe-root
LAYOUT
udevadm settle
mkfs.fat -n PROBEESP "${device}p1" >"$work/format.log"
mkfs.fat -n PROBEXBOOT "${device}p2" >>"$work/format.log"
mkfs.ext4 -q -O verity "${device}p3"
mkdir -p "$work/target" "$work/inputs"
mount "${device}p3" "$work/target"
mkdir -p "$work/target/boot" "$work/target/efi"
mount "${device}p2" "$work/target/boot"
mount "${device}p1" "$work/target/efi"
mount -o ro /dev/disk/by-label/FINITEINPUTS "$work/inputs"
# Generic image mode suppresses firmware changes. The target is a fresh loop
# filesystem, never the booted VM root and never an existing OSTree system.
status=0
bootc install to-filesystem --composefs-backend --bootloader systemd \
  --generic-image --skip-finalize --skip-fetch-check \
  --source-imgref "oci-archive:$work/inputs/base.oci.tar" \
  --target-transport oci-archive --target-imgref /inputs/base.oci.tar \
  "$work/target" >"$work/install.log" 2>&1 || status=$?
python3 - "$work" "$status" <<'PY'
import json, pathlib, subprocess, sys
work, status = pathlib.Path(sys.argv[1]), int(sys.argv[2])
paths = {}
for name, mount in [('esp', 'efi'), ('xbootldr', 'boot')]:
    paths[name] = sorted(str(p.relative_to(work / 'target' / mount))
                         for p in (work / 'target' / mount).rglob('*') if p.is_file())
print(json.dumps({'schema': 1, 'bootc': subprocess.check_output(['bootc', '--version'], text=True).strip(),
    'scope': 'file placement on a fresh disposable loop disk; not encrypted coexistence or boot acceptance',
    'xbootldrBytes': 4 * 1024**3, 'installExitCode': status, 'files': paths,
    'ukisOnXbootldr': any(p.startswith('EFI/Linux/') and p.endswith('.efi') for p in paths['xbootldr']),
    'ukisOnEsp': any(p.startswith('EFI/Linux/') and p.endswith('.efi') for p in paths['esp']),
    'installLog': (work / 'install.log').read_text(errors='replace')}, indent=2))
PY
