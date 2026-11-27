# EFI updates and recovery

Native images distribute Fedora shim and MokManager, together with
systemd-boot signed by the production boot certificate. The sealed root's
`/usr/lib/finite/efi/manifest.json` binds these payload bytes and the public
certificate fingerprint. `finite-efi-update.service` verifies the payload and
refreshes the ESP after a native boot. It skips OSTree systems.

The managed files are `EFI/finite/{shimx64,mmx64,grubx64}.efi` and
`EFI/systemd/systemd-bootx64.efi`. Shim's `grubx64.efi` is the signed systemd-boot
loader. The updater does not create firmware entries or change BootOrder.
It does not remove old Fedora, GRUB or rEFInd files.

Fallback-file ownership is per machine. During coexistence, the default is
`manageFallback: false`, preserving the existing fallback. Only a qualified
fresh installation or accepted migration should enable it using
`/etc/finite/bootloader.json`:

```json
{"schema": 1, "manageFallback": true}
```

With that setting the updater also manages `EFI/BOOT/BOOTX64.EFI` (Fedora shim)
and its sibling `grubx64.efi` and `mmx64.efi`. This setting does not enroll keys.
Keep the existing module-signing MOK as well as the production boot MOK.

Before any FAT write, the updater saves all previous bytes and a fsynced
journal under `/var/lib/finite/efi-updates/GENERATION`. It reserves 32 MiB of
ESP space beyond the replacement files. Each replacement is written through a
temporary file, fsynced, renamed and verified. An interrupted prepared journal
blocks another update until explicit recovery. Successful journals are retained
so an image rollback can be paired with EFI recovery when necessary.

From a trusted rescue system, mount the intended native root and its ESP.
Inspect its root-private journals to identify the generation. Run the matching
helper as root, giving the actual rescue mount paths:

```bash
python3 /mnt/native/usr/libexec/finite/update-efi \
  --esp /mnt/esp --state /mnt/native/var/lib/finite/efi-updates \
  --recover GENERATION
```

The journal binds the FAT filesystem UUID, so a rescue mount can use a different
path. The helper rejects a different ESP identity. Ensure the state path points
to the affected system's persistent `/var`, including a separately mounted
`/var` where applicable. Recovery works without a native kernel boot and does
not require the private signing key. A read-only ESP is temporarily remounted
writable and returned to read-only afterwards.

Recovery checks the entire set before restoring anything. If a file differs
from both its recorded previous and replacement bytes, it refuses automatic
recovery. Preserve that state and use verified rescue artifacts to resolve the
external change. Never delete the journal merely to permit another update.

File-level failure tests cover interruption at every write, previous-generation
restoration, unknown external edits, space exhaustion, path escapes and
idempotence. The scratch-FAT VM test also passed on 2026-11-18 UTC: all seven
write interruptions recovered, a committed generation restored after remount,
and `fsck.fat -n` reported a clean filesystem. It uses inert file payloads and
does not qualify the firmware trust chain. Shim/SBAT, an actual loader-version
change and rescue boot remain release qualification requirements.
