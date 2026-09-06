#!/usr/bin/env bash
# Exercise the actual ISO/FAT editors with a tiny synthetic Lorax layout.
set -euo pipefail
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/tree/EFI/BOOT" "$work/tree/boot/grub2"
for menu in bios efi embedded; do
  printf '# %s menu\nset default="1"\nset timeout=60\nmenuentry install {\n linux /vmlinuz quiet\n}\n' \
    "$menu" >"$work/$menu.cfg"
done
cp "$work/bios.cfg" "$work/tree/boot/grub2/grub.cfg"
cp "$work/efi.cfg" "$work/tree/EFI/BOOT/grub.cfg"
mformat -i "$work/efi.img" -C -T 24576 ::
mmd -i "$work/efi.img" ::/EFI ::/EFI/BOOT
mcopy -i "$work/efi.img" "$work/embedded.cfg" ::/EFI/BOOT/grub.cfg
xorriso -as mkisofs -R -J -V FINBOX_FIXTURE -o "$work/source.iso" \
  -append_partition 2 0xef "$work/efi.img" -appended_part_as_gpt \
  -e '--interval:appended_partition_2:all::' -no-emul-boot "$work/tree"
sha256sum "$work/source.iso" >"$work/source.sha256"
printf 'poweroff\n' >"$work/ks.cfg"
bash scripts/bluebuild/prepare-vm-iso.sh "$work/source.iso" "$work/ks.cfg" "$work/prepared"
mkdir "$work/verified"
xorriso -osirrox on -indev "$work/prepared/install.iso" \
  -extract /boot/grub2/grub.cfg "$work/verified/bios.cfg" \
  -extract /EFI/BOOT/grub.cfg "$work/verified/efi.cfg" \
  -extract /ks.cfg "$work/verified/ks.cfg" \
  -extract_boot_images "$work/verified/boot"
mcopy -i "$work/verified/boot/gpt_part2_efi.img" ::/EFI/BOOT/grub.cfg "$work/verified/embedded.cfg"
mcopy -i "$work/verified/boot/eltorito_img1_uefi.img" ::/EFI/BOOT/grub.cfg "$work/verified/eltorito.cfg"
for menu in bios efi embedded; do
  grep -qF "# $menu menu" "$work/verified/$menu.cfg"
done
for config in "$work/verified/"{bios,efi,embedded,eltorito}.cfg; do
  grep -qxF 'set default="0"' "$config"
  grep -qxF 'set timeout=1' "$config"
  grep -qF 'console=ttyS0,115200n8 inst.ks=cdrom:/ks.cfg' "$config"
done
cmp "$work/ks.cfg" "$work/verified/ks.cfg"
sha256sum -c "$work/source.sha256"
