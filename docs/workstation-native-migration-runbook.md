# Workstation native migration runbook

The operator carries out this parallel installation from verified rescue media.
It keeps the existing OSTree `/root`, ext4 `/boot`, EFI files and firmware boot
order, and stages `finite-native` in a second Btrfs root. The commands below
apply only to the recorded 512,110,190,592-byte workstation disk.

## Rehearsal evidence

Run `45992389140` passed on source `c2500e1d4be689664132ff330043b72a514ba58c`
with one 2-vCPU, 3072 MiB guest at a time and a 3072 MiB host reserve. Its
raw records verify that the original root booted after an interruption before
the GPT write, an interruption after the first EFI write, and a BootNext that
pointed to a missing loader. The last fork booted the sealed native root once
using a second LUKS keyslot and then booted the original default. All six disk
boots retained the shared home data, `/nix` and numeric ownership. Secure Boot
and SELinux stayed enabled and enforcing. The native boot also passed full
preflight and enforced fs-verity. [Rehearsal evidence](https://github.com/closure-labs/finite/actions/runs/45992389140/artifacts/15205435307)

The fixture used a disposable signing key, synthetic LUKS passphrases and
OVMF with Fedora shim and GRUB. Production signing, interactive MOK enrollment,
the workstation's rEFInd and firmware path, its data and optional FIDO2 unlock
need their own checks. [Rollout record](native-rollout-progress.md)

## Prepare on the existing installation

1. Wait for the reviewed production seal and VM qualification for the exact
   immutable `finite-native` digest. Obtain the ISO, `installation.json` and
   `SHA256SUMS` from the corresponding trusted main workflow. In the artifact
   directory run `sha256sum --check SHA256SUMS` and
   `jq -e '.validationOnly == false and (.migrationRehearsal // false) == false' installation.json`.
   Verify the manifest with
   `cosign verify --key "$repo/cosign.pub" "$(jq -er .payload installation.json)"`.
   `repo` is the reviewed Finite checkout. Compare the payload, ISO and signing
   identities to the production qualification evidence. Test-boot this media
   before starting the migration.
2. From the checkout run `bash scripts/workstation/backup-local.sh` as the
   workstation user. It captures GPT, LUKS header, firmware, credential and
   selected configuration and runs `recovery-backup.py verify`. Confirm the
   resulting `verified.json` records the restore and password-store check, and
   that the encrypted archive is available independently of the workstation.
   Verify your separate documents backup too. The configuration inventory
   excludes documents. Keep the recovery data and its passphrase separately.
3. Verify the production MOK DER fingerprint against the reviewed pin before
   queuing enrollment. Run the following from the checkout and complete any
   required enrollment in MokManager. Keep the existing module-signing MOK.

   ```bash
   cert=$(mktemp /tmp/finite-production-mok.XXXXXXXX)
   openssl x509 -in files/system/usr/share/finite/secure-boot/finite-boot.pem \
     -outform DER -out "$cert"
   printf '%s  %s\n' "$(jq -er .certificateDerSha256 sources/boot-signing.json)" "$cert" | sha256sum -c
   sudo bash -c 'cd "$(mktemp -d /run/finite-mok.XXXXXXXX)" && mokutil --export && sha256sum -- *.der'
   ```

   If the pinned fingerprint is missing, run `sudo mokutil --import "$cert"`
   and reboot into MokManager. After reboot verify enrollment and run
   `mokutil --sb-state`. The previously enrolled trial certificate is a
   different key. Keep Secure Boot enabled throughout the migration.

4. Boot the existing default once, with no deployment staged. Record
   `sudo efibootmgr -v`, `cat /proc/cmdline`, `findmnt --mountpoint /sysroot`,
   `findmnt --mountpoint /var/home`, `findmnt --mountpoint /nix`, `id`,
   `getent passwd "$(id -un)"`, `getent group "$(id -g)"`,
   `ls -l /dev/disk/by-id/` and
   `hostnamectl --static` in the private operator records. Confirm `/sysroot`
   is Btrfs `/root`, `/var/home` is Btrfs `/home`, and `/nix` is persistent.
   Record a sample document's SHA-256 and `stat -c '%u:%g'` output and the
   active Home Manager generation. The working legacy GRUB entry must contain
   the current root filesystem UUID, explicit `rootflags=subvol=/root` and
   `ostree=`. If the subvolume flag is absent and there is no existing
   `rootflags=`, add it with
   `sudo rpm-ostree kargs --append-if-missing=rootflags=subvol=/root`, reboot the
   same legacy path, and verify the resulting command line before proceeding.
   If a different `rootflags=` is present, review it before changing anything.

## Verify the rescue boot and disk identity

Select the production media through Dell's F12 menu. Use a root rescue console
on the live system with the whole-disk installer masked. To test the console,
edit the live GRUB entry and append
`systemd.mask=finite-native-installer.service systemd.debug_shell=1`, then open
the local debug shell on tty9. Use this console only during the physically
attended rescue session. Keep `finite.native-installer=1` in the live command
line. Confirm `systemctl show -p LoadState --value finite-native-installer.service`
reports `masked`. Test the console and the pinned tools with Secure Boot enabled
before the migration. Stop if the production media do not provide this path.

Use one root Bash session for the rescue commands. Set `records` to a new
private directory on a mounted encrypted external recovery volume. Point `repo`
to the corresponding read-only checkout on that volume. Enter the verified
legacy BootOrder from step 4 when prompted. Confirm both existing LUKS secrets
work at the two interactive prompts. Leave the LUKS header and tokens intact.

```bash
set -euo pipefail
umask 077
test "$(id -u)" = 0
test -d /sys/firmware/efi/efivars
grep -qw 'finite.native-installer=1' /proc/cmdline
test "$(systemctl show -p LoadState --value finite-native-installer.service)" = masked
test "$(mokutil --sb-state | sed -n '1p')" = 'SecureBoot enabled'
read -r -p 'Private external records directory: ' records
mkdir -m 0700 -- "$records"
findmnt -T "$records"
read -r -p 'Reviewed checkout on external volume: ' repo
test -f "$repo/scripts/workstation/systemd-boot-preflight.py"
read -r -p 'BootOrder from the running legacy installation: ' old_order
efibootmgr -v | tee "$records/firmware-before.txt"
grep -Fx "BootOrder: $old_order" "$records/firmware-before.txt"
if grep -q '^BootNext:' "$records/firmware-before.txt"; then exit 1; fi

disk=/dev/nvme0n1
read -r -p 'Recorded whole-disk /dev/disk/by-id path: ' disk_id
[[ $disk_id == /dev/disk/by-id/nvme-* && -L $disk_id ]]
test "$(readlink -f "$disk_id")" = "$disk"
esp=${disk}p1
legacy_boot=${disk}p7
encrypted=${disk}p8
xbootldr=${disk}p9
mapper=finite-migration
mapped=/dev/mapper/$mapper
work=$(mktemp -d /run/finite-migration.XXXXXXXX)
top=$work/top
target=$work/target
deployment=$work/deployment
mkdir "$top" "$target" "$deployment"

test "$(blockdev --getsize64 "$disk")" = 512110190592
test "$(blockdev --getss "$disk")" = 512
test "$(lsblk -dnro PARTUUID "$esp")" = 5bc0db94-2336-4824-b55c-1c6d8395221b
test "$(cryptsetup luksUUID "$encrypted")" = c9dbefef-23cd-4ca8-86f2-8332f16e8bd4
test "$(blkid -s TYPE -o value "$legacy_boot")" = ext4
test ! -e "$mapped"
lsblk -J -o PATH,TYPE,MOUNTPOINTS "$disk" | jq -e \
  'all(.blockdevices[] | recurse(.children[]?); all(.mountpoints[]?; . == null or . == "")) and
   all(.blockdevices[0].children[]; .type == "part" and (.children // [] | length) == 0)'
cryptsetup open --type luks2 --test-passphrase "$encrypted"
cryptsetup open --type luks2 --test-passphrase "$encrypted"
sfdisk --dump "$disk" > "$records/original.sfdisk"
sfdisk --json "$disk" > "$records/original.gpt.json"
```

Check that `findmnt -T "$records"` names the external volume and that `lsblk`
shows the expected NVMe by-id and no active mappings, mounts or swap.
Before any disk write, authenticate the embedded native payload and verify the
bootc binary using the installer checks. `payload` is the qualified production
`sha256:…` manifest digest from the trusted ISO metadata.

```bash
read -r -p 'Qualified production payload digest: ' payload
python3 - "$payload" <<'PY'
import runpy
import sys

installer = runpy.run_path('/usr/libexec/finite/finite-native-install')
load_pins = installer['load_pins']
check_environment = installer['check_environment']
verify_payload = installer['verify_payload']
pins = load_pins()
check_environment(pins)
verify_payload(pins)
assert pins['payloadDigest'] == sys.argv[1]
assert pins['targetImgref'] == 'ghcr.io/closure-labs/finite:finite-native'
PY
rescue_fingerprint=$(openssl x509 -in /usr/share/finite/secure-boot/finite-boot.pem -outform DER |
  sha256sum | cut -d' ' -f1)
test "$rescue_fingerprint" = "$(jq -er .certificateDerSha256 "$repo/sources/boot-signing.json")"
```

## Shrink the filesystem, mapping and partition

End sectors in this table are exclusive. Expected sizes are based on 512-byte
sectors. The new Btrfs device size leaves 64 MiB unused inside the mapping.

| Partition | Start | Old end | New end | New GPT type |
| --- | ---: | ---: | ---: | --- |
| p1 | 2048 | 1230848 | 1230848 | ESP |
| p7 | 1230848 | 5425152 | 5425152 | Linux filesystem |
| p8 | 5425152 | 1000214528 | 991825920 | x86-64 root |
| p9 | 991825920 | | 1000214528 | XBOOTLDR |

Generate a proposed table from the saved dump so the disk UUID and existing
partition UUIDs, names and attributes carry forward. Refuse any other geometry.
The dry run must pass before opening the root for the shrink.

```bash
python3 - "$disk" "$records" <<'PY'
import json
from pathlib import Path
import re
import sys

disk, records = sys.argv[1], Path(sys.argv[2])
original = json.loads((records / 'original.gpt.json').read_text())['partitiontable']
legacy = {1: (2048, 1230848), 7: (1230848, 5425152), 8: (5425152, 1000214528)}
types = {1: 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b',
         7: '0fc63daf-8483-4772-8e79-3d69d8477de4',
         8: '0fc63daf-8483-4772-8e79-3d69d8477de4'}
assert (original['device'], original['label'], original['unit'], original['sectorsize']) == (disk, 'gpt', 'sectors', 512)
expected = {f'{disk}p{n}': (start, end - start, types[n]) for n, (start, end) in legacy.items()}
assert {p['node']: (p['start'], p['size'], p['type'].lower()) for p in original['partitions']} == expected
source = (records / 'original.sfdisk').read_text()
lines = source.splitlines()
position, = (i for i, line in enumerate(lines) if re.match(re.escape(disk) + r'p8\s*:', line))
line, count = re.subn(r'(size=\s*)\d+', r'\g<1>986400768', lines[position])
assert count == 1
lines[position], count = re.subn(r'(type=)[0-9A-Fa-f-]+', r'\g<1>4f68bce3-e8cd-4db1-96e7-fbcaf984b709', line)
assert count == 1
lines.append(f'{disk}p9 : start=991825920, size=8388608, type=bc13c2ff-59e6-4262-a352-b275fd6f7172')
(records / 'native.sfdisk').write_text('\n'.join(lines) + '\n')
PY
sfdisk --no-act --wipe never --wipe-partitions never "$disk" < "$records/native.sfdisk"
cryptsetup open --type luks2 "$encrypted" "$mapper"
fsuuid=$(blkid -s UUID -o value "$mapped")
read -r -p 'Filesystem UUID from the running legacy root=UUID= argument: ' legacy_root_uuid
test "$fsuuid" = "$legacy_root_uuid"
cryptsetup luksDump --dump-json-metadata "$encrypted" | jq -e \
  '.segments | keys == ["0"] and .["0"].type == "crypt" and
   (.["0"].offset | tonumber) == 16777216'
test "$(blockdev --getsize64 "$mapped")" = 509315383296
mount -o subvolid=5 "$mapped" "$top"
btrfs subvolume show "$top/root"
btrfs subvolume show "$top/home"
test ! -e "$top/root-native"
btrfs subvolume get-default "$top" | tee "$records/btrfs-default-before.txt"
btrfs filesystem usage -b "$top"
btrfs filesystem resize 504953307136 "$top"
btrfs filesystem show --raw "$top" | awk '
  $1 == "devid" { count++; if ($2 != 1 || $3 != "size" || $4 != 504953307136) exit 1 }
  END { if (count != 1) exit 1 }'
umount "$top"
cryptsetup resize --size 986368000 "$mapper"
test "$(blockdev --getsz "$mapped")" = 986368000
cryptsetup close "$mapper"
sync
```

At this checkpoint the GPT is still the original. Verify the dump still
matches, then write the proposed table once. Validate every preserved entry
with `sfdisk` before formatting only p9.

```bash
sfdisk --dump "$disk" | cmp "$records/original.sfdisk" -
sfdisk --wipe never --wipe-partitions never "$disk" < "$records/native.sfdisk"
udevadm settle
sfdisk --verify "$disk"
sfdisk --json "$disk" | tee "$records/native.gpt.json"
jq -e -s '
  .[0].partitiontable as $old | .[1].partitiontable as $new |
  $old.id == $new.id and $old.sectorsize == $new.sectorsize and
  ($new.partitions | length) == 4 and
  $new.partitions[0:2] == $old.partitions[0:2] and
  ($new.partitions[2] | del(.size, .type)) == ($old.partitions[2] | del(.size, .type)) and
  $new.partitions[2].size == 986400768 and
  ($new.partitions[2].type | ascii_downcase) == "4f68bce3-e8cd-4db1-96e7-fbcaf984b709" and
  $new.partitions[3].start == 991825920 and $new.partitions[3].size == 8388608 and
  ($new.partitions[3].type | ascii_downcase) == "bc13c2ff-59e6-4262-a352-b275fd6f7172"
' "$records/original.gpt.json" "$records/native.gpt.json"
cryptsetup open --type luks2 "$encrypted" "$mapper"
test "$(blockdev --getsz "$mapped")" = 986368000
test "$(blkid -s UUID -o value "$mapped")" = "$fsuuid"
btrfs check --readonly "$mapped"
test "$(lsblk -dnro PARTTYPE "$xbootldr")" = bc13c2ff-59e6-4262-a352-b275fd6f7172
mkfs.fat -F 32 -n XBOOTLDR "$xbootldr"
```

## Stage the separate native root and EFI entry

Mount the new root, existing ESP and new XBOOTLDR at distinct paths. The ext4
legacy `/boot` stays unmounted. Save the complete original ESP off the disk
before calling bootc. The native install can write the fallback path through
bootctl. The next block restores just that path and verifies the original EFI
trees before accepting the install. On any error preserve the recorded ESP
and follow the recovery section.

```bash
mount -o subvolid=5 "$mapped" "$top"
btrfs subvolume create "$top/root-native"
mount -o subvol=/root-native "$mapped" "$target"
mount --mkdir "$esp" "$target/efi"
mount --mkdir "$xbootldr" "$target/boot"
test -f "$target/efi/EFI/fedora/shimx64.efi"
tar -cf "$records/esp-before.tar" -C "$target/efi" .
mkdir "$work/esp-before"
tar -xf "$records/esp-before.tar" -C "$work/esp-before"
mkdir "$top/native-scratch"
mount --bind "$top/native-scratch" /var/tmp
pin_file=/usr/lib/finite/installer/pins.json
source_ref=$(jq -er .sourceImgref "$pin_file")
target_ref=$(jq -er .targetImgref "$pin_file")
result=0
bootc install to-filesystem --composefs-backend --bootloader systemd \
  --generic-image --skip-fetch-check --skip-finalize \
  --source-imgref "$source_ref" --target-imgref "$target_ref" "$target" || result=$?
umount /var/tmp

python3 - "$work/esp-before" "$target/efi" <<'PY'
from pathlib import Path
import sys

saved, esp = map(Path, sys.argv[1:])
old_boot, live_boot = saved / 'EFI/BOOT', esp / 'EFI/BOOT'
old = [path for path in old_boot.iterdir() if path.name.casefold() == 'bootx64.efi'] if old_boot.is_dir() else []
live = [path for path in live_boot.iterdir() if path.name.casefold() == 'bootx64.efi'] if live_boot.is_dir() else []
assert len(old) <= 1 and len(live) <= 1
if live and (not old or live[0].name != old[0].name):
    live[0].unlink()
if old:
    source, = old
    live_boot.mkdir(parents=True, exist_ok=True)
    destination = live_boot / source.name
    expected = source.read_bytes()
    if not destination.exists() or destination.read_bytes() != expected:
        destination.write_bytes(expected)
PY

for directory in fedora refind BOOT; do
  if [[ -d "$work/esp-before/EFI/$directory" ]]; then
    diff -qr "$work/esp-before/EFI/$directory" "$target/efi/EFI/$directory"
  fi
done
test "$result" = 0
bootc install mount --sysroot "$target" --latest "$deployment"
python3 - "$deployment" "$target" <<'PY'
from pathlib import Path
import runpy
import sys

deployment, target = map(Path, sys.argv[1:])
installer = runpy.run_path('/usr/libexec/finite/finite-native-install')
verify_placement = installer['verify_placement']
configure_target = installer['configure_target']
verify_placement(target)
configure_target(deployment, target)
(deployment / 'etc/finite/bootloader.json').write_text('{"schema":1,"manageFallback":false}\n')
PY
if awk '$1 !~ /^#/ && $2 == "/var/home" { found = 1 } END { exit !found }' "$deployment/etc/fstab"; then exit 1; fi
printf '\nUUID=%s /var/home btrfs subvol=/home 0 0\n' "$fsuuid" >> "$deployment/etc/fstab"
```

Enter the account and primary group values from step 4. Check the destination
account database for collisions first. The commands below assume neither name
nor numeric ID exists on the new image. Keep the same login home and explicitly
restore required supplementary groups that exist in the native image. Set the
login password interactively. Apply the saved hostname and any required network
configuration from the verified backup with its original ownership and mode.
Leave the native `/etc/fstab`, `/etc/crypttab` and service configuration in place.

```bash
read -r -p 'Existing account name, UID, primary group name, and GID: ' account uid group gid
[[ $uid =~ ^[0-9]+$ && $gid =~ ^[0-9]+$ ]]
test "$(stat -c '%u:%g' "$top/home/$account")" = "$uid:$gid"
groupadd --root "$deployment" --gid "$gid" "$group"
useradd --root "$deployment" --no-create-home --uid "$uid" --gid "$gid" \
  --home-dir "/var/home/$account" "$account"
passwd --root "$deployment" "$account"
# Apply only if the saved account belongs to wheel.
# usermod --root "$deployment" --append --groups wheel "$account"
read -r -p 'Saved static hostname: ' hostname
printf '%s\n' "$hostname" > "$deployment/etc/hostname"
chroot "$deployment" restorecon -RF /etc/finite /etc/fstab /etc/passwd \
  /etc/shadow /etc/group /etc/gshadow /etc/hostname

state=$deployment/var/lib/finite/efi-updates
updater=/usr/libexec/finite/update-efi
python3 "$updater" --esp "$target/efi" --state "$state" --install-root "$deployment"
chroot "$deployment" restorecon -RF /var/lib/finite/efi-updates
for directory in fedora refind BOOT; do
  if [[ -d "$work/esp-before/EFI/$directory" ]]; then
    diff -qr "$work/esp-before/EFI/$directory" "$target/efi/EFI/$directory"
  fi
done
test -f "$target/efi/EFI/finite/shimx64.efi"
btrfs subvolume set-default "$top/root-native"
btrfs subvolume get-default "$top"
umount --recursive "$deployment"
umount --recursive "$target"
umount "$top"
cryptsetup close "$mapper"
sync
```

Create a separate firmware entry without adding it to the default order. Read
back the new entry and compare its ESP partition UUID and file path before
arming it. Use the new entry number, since firmware numbers differ from the VM.

```bash
efibootmgr -v | tee "$records/firmware-pre-arm.txt"
grep -Fx "BootOrder: $old_order" "$records/firmware-pre-arm.txt"
if grep -Eq '^BootNext:|^Boot[0-9A-Fa-f]{4}\*?\s+Finite native\s' "$records/firmware-pre-arm.txt"; then exit 1; fi
efibootmgr --create-only --disk "$disk" --part 1 --label 'Finite native' --loader '\EFI\finite\shimx64.efi'
efibootmgr -v | tee "$records/firmware-native-entry.txt"
grep -Fx "BootOrder: $old_order" "$records/firmware-native-entry.txt"
esp_uuid=$(lsblk -dnro PARTUUID "$esp")
entry=$(grep -Ei "^Boot[0-9a-f]{4}\\*?[[:space:]]+Finite native[[:space:]]+HD\(1,GPT,$esp_uuid," "$records/firmware-native-entry.txt")
grep -Fi '\EFI\finite\shimx64.efi' <<< "$entry"
native_id=${entry:4:4}
[[ $native_id =~ ^[0-9A-Fa-f]{4}$ && ,$old_order, != *,$native_id,* ]]
efibootmgr --bootnext "$native_id"
efibootmgr | tee "$records/firmware-armed.txt"
grep -Fx "BootNext: $native_id" "$records/firmware-armed.txt"
grep -Fx "BootOrder: $old_order" "$records/firmware-armed.txt"
```

## Accept the one-time boot and the original default

Remove the rescue media and reboot. Enter the recovery key for the native trial
and keep the primary passphrase available. Verify these checkpoints from the
native desktop before the next reboot. Save the preflight and the exact root
digest with the operator records.

```bash
sudo efibootmgr -v
sudo python3 scripts/workstation/systemd-boot-preflight.py
sudo bootc status --json | jq -e '.status.booted.composefs |
  .bootloader == "systemd" and .bootType == "Uki" and .missingVerityAllowed == false'
findmnt -no SOURCE,FSTYPE,FSROOT --mountpoint /sysroot
findmnt -no SOURCE,FSTYPE --mountpoint /efi
findmnt -no SOURCE,FSTYPE --mountpoint /boot
findmnt -no SOURCE,FSROOT --mountpoint /var/home
findmnt --mountpoint /nix
id
getenforce
cat /proc/cmdline
```

Confirm BootCurrent is the new entry and BootNext was consumed. BootOrder
must still match the original. Preflight must report no blockers, systemd-boot,
`\EFI\finite\grubx64.efi`, systemd-stub and active lockdown. Confirm the signed
`composefs.digest` is the qualified production digest, `/sysroot` is
`/root-native`, `/boot` is p9 (VFAT) and `/efi` is p1. Check that SELinux is
enforcing, `/var/home` is `/home`, the sample document's digest and UID/GID
match, and the same Home Manager generations are available. Check desktop
login, credentials, networking, graphics and suspend/resume.

Reboot normally with no BootNext. Verify the original rEFInd/GRUB path, the
same BootOrder, explicit OSTree `/root`, ext4 `/boot`, the shared data and
`/nix` again. Keep the legacy default through a real native update and rollback
and the remaining hardware acceptance checks. Treat FIDO2 as a separate
exercise after a sealed-UKI VM test, keeping both existing secrets available.

## Recover at the last verified checkpoint

| Interruption | Recovery |
| --- | --- |
| Before GPT write | Leave the original table in place. Open the legacy firmware path and verify the original root and data. The smaller Btrfs filesystem can remain inside the unchanged partition. |
| After GPT write or partial native staging | Verify GPT, Btrfs and the saved legacy EFI trees before choosing the old firmware path. If bootc was interrupted while writing its fallback, use the saved ESP archive and the fallback restoration in the staging section. If a geometry or integrity check failed, stop writes and inspect the saved table and header from rescue. |
| EFI updater stopped with a prepared journal | From verified rescue media reopen LUKS, mount `/root-native` at the staging target and its deployment with `bootc install mount`. Mount p1 at the target's `/efi`. Recover the exact prepared journal as shown below, then verify the saved Fedora, rEFInd and fallback files before entering the old system. |
| Native entry failed or boot hung after firmware handed off | Reboot via F12 into the proved original path. If BootNext remains armed, clear only that variable with `efibootmgr --delete-bootnext` from rescue and recheck the original BootOrder. |

In the EFI case, verify the disk, partitions, LUKS UUID and rescue media again.
Compare the current GPT to `native.gpt.json`. If the original rescue session
is gone, mount the staging paths again with the following commands. `disk`,
`esp`, `encrypted`, `xbootldr`, `mapper` and `mapped` use the same verified
values as above. Leave the old root and ext4 `/boot` unmounted.

```bash
work=$(mktemp -d /run/finite-efi-recovery.XXXXXXXX)
target=$work/target
deployment=$work/deployment
mkdir "$target" "$deployment"
cryptsetup open --type luks2 "$encrypted" "$mapper"
mount -o subvol=/root-native "$mapped" "$target"
mount --mkdir "$esp" "$target/efi"
mount --mkdir -o ro "$xbootldr" "$target/boot"
bootc install mount --sysroot "$target" --latest "$deployment"
state=$deployment/var/lib/finite/efi-updates
```

Use the saved generation whose `journal.json` says `prepared` and whose ESP
UUID matches the mounted p1. The updater validates the whole recovery set
before restoring files.

```bash
find "$state" -mindepth 2 -maxdepth 2 -name journal.json -print
read -r -p 'Prepared EFI journal generation: ' generation
jq -e '.phase == "prepared"' "$state/$generation/journal.json"
python3 /usr/libexec/finite/update-efi --esp "$target/efi" --state "$state" --recover "$generation"
jq -e '.phase == "recovered"' "$state/$generation/journal.json"
```

Return to the original system before deciding whether to resume. The old GRUB
entry explicitly selects `/root` even if the Btrfs default is `root-native`.
If restoring the original Btrfs default is necessary, use the recorded
subvolume ID from `btrfs-default-before.txt` with
`btrfs subvolume set-default "$original_id" "$top"` from rescue. Keep both
roots, p9, the original EFI directories and all recovery records until
acceptance. Restoring an original GPT over a changed filesystem layout or
rewriting a LUKS header requires diagnosis of the current disk and the saved
backup before either write.
