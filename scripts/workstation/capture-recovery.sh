#!/usr/bin/env bash
# Read the selected disk; write recovery files only to a new private directory.
set -euo pipefail
disk=${1:?whole disk device required}
luks=${2:?LUKS partition device required}
output=${3:?new private output directory required}
[[ $EUID == 0 && -b $disk && -b $luks && ! -e $output ]]
[[ $(lsblk -dnro TYPE "$disk") == disk ]]
[[ $(lsblk -dnro PKNAME "$luks") == "$(basename "$(readlink -f "$disk")")" ]]
cryptsetup isLuks "$luks"
umask 077
mkdir -m 0700 -- "$output"
lsblk --json --bytes --output NAME,PATH,TYPE,SIZE,FSTYPE,UUID,PARTUUID,MOUNTPOINTS >"$output/lsblk.json"
sfdisk --dump "$disk" >"$output/partition-table.sfdisk"
cryptsetup luksHeaderBackup "$luks" --header-backup-file "$output/luks-header.bin"
efibootmgr --verbose >"$output/firmware-entries.txt"
cat /proc/cmdline >"$output/cmdline.txt"
findmnt --json >"$output/mounts.json"
cp --preserve=all /etc/fstab "$output/fstab"
cp --preserve=all /etc/crypttab "$output/crypttab"
esp=$(findmnt --noheadings --output TARGET --mountpoint /boot/efi)
[[ $esp == /boot/efi && $(findmnt -nro FSTYPE --mountpoint "$esp") == vfat ]]
mapfile -d '' efi_config < <(find "$esp" -type f \( -name '*.conf' -o -name '*.csv' -o -name '*.der' -o -name '*.cer' \) -printf '%P\0')
tar --create --file="$output/efi-configuration.tar" --directory="$esp" --files-from=/dev/null -- "${efi_config[@]}"
# Preserve unique keys/configuration; kernels, UKIs and EFI binaries are rebuildable.
if [[ -d /var/lib/finite-boot-trial ]]; then
  tar --create --file="$output/boot-signing.tar" --directory=/var/lib/finite-boot-trial/output MOK.key MOK.pem MOK.der certificate.txt
fi
selected_etc=(passwd group shadow gshadow hostname)
for entry in NetworkManager/system-connections ssh; do
  if [[ -e /etc/$entry ]]; then selected_etc+=("$entry"); fi
done
tar --create --acls --xattrs --numeric-owner --file="$output/selected-etc.tar" --directory=/etc -- "${selected_etc[@]}"
(
  cd "$output"
  mapfile -d '' recovery_files < <(find . -type f -print0 | sort -z)
  sha256sum -- "${recovery_files[@]}" >SHA256SUMS
)
echo 'Recovery files captured. Include this entire private directory in the encrypted backup.'
