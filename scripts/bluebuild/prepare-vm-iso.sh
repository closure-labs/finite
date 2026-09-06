#!/usr/bin/env bash
set -euo pipefail
source_iso="${1:?source ISO required}"
kickstart="${2:?kickstart file required}"
state="${3:?temporary output directory required}"
mkdir -p "$state"
# Lorax has separate BIOS, ISO UEFI, and appended EFI-partition menus.
# Updating only /boot/grub2/grub.cfg leaves UEFI on the interactive media test.
xorriso -osirrox on -indev "$source_iso" \
  -extract /boot/grub2/grub.cfg "$state/grub-bios.cfg" \
  -extract /EFI/BOOT/grub.cfg "$state/grub-efi.cfg" \
  -extract_boot_images "$state/boot-images"
efi="$state/boot-images/gpt_part2_efi.img"
test -s "$efi"
mcopy -i "$efi" ::/EFI/BOOT/grub.cfg "$state/grub-efi-embedded.cfg"
for config in "$state"/grub-*.cfg; do
  sed -i -e 's/quiet/console=ttyS0,115200n8 inst.ks=cdrom:\/ks.cfg/g' \
    -e 's/set default=.*/set default="0"/' -e 's/set timeout=.*/set timeout=1/' "$config"
  grep -qF 'inst.ks=cdrom:/ks.cfg' "$config"
done
mcopy -o -i "$efi" "$state/grub-efi-embedded.cfg" ::/EFI/BOOT/grub.cfg
xorriso -indev "$source_iso" -outdev "$state/install.iso" -boot_image any replay \
  -append_partition 2 0xef "$efi" \
  -map "$kickstart" /ks.cfg -chmod 0444 /ks.cfg -- \
  -map "$state/grub-bios.cfg" /boot/grub2/grub.cfg \
  -map "$state/grub-efi.cfg" /EFI/BOOT/grub.cfg
