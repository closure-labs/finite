# Native installer prototype

This is experimental whole-disk media, not the workstation migration tool.
It has source-level tests but no end-to-end ISO or encrypted Secure Boot
qualification. It erases the selected disk. Do not use it to convert an existing
OSTree installation or preserve its data. The parallel workstation migration
remains gated by the [rollout record](../../docs/native-rollout-progress.md).

Build media only on the ephemeral hosted runner, using an authenticated native
payload in `ghcr.io/closure-labs/finite` and its distinct `finite-native` or
`finite-native-dev` tag. The build verifies the exact digest with `cosign.pub`,
checks its native profile, restores the preserved kernel from `/kernel` for live
boot, and records the payload digest and bootc binary hash in schema-3 pins.
The target payload remains a separate OCI layout in the live filesystem. Its
manifest and compressed layer bytes survive ISO assembly in their original
form. The installer reads this layout offline and keeps the native update tag
as its installed target reference. The uploaded ISO is explicitly unqualified.

Boot the media in UEFI mode. From its rescue console, the read-only command is:

```sh
/usr/libexec/finite/finite-native-install plan
```

The preview currently uses the same disk-selection and typed-ID prompts as the
installer; it prints commands and does not execute them. `install` additionally
asks for a LUKS passphrase and repeats disk identity/eligibility checks just before
partitioning. It refuses mounted disks, swap, active block-device holders,
read-only disks, disks smaller than 64 GiB and disks without a stable by-id name.
The layout is a 600 MiB ESP, a 4 GiB VFAT XBOOTLDR and an ext4/fs-verity root
inside LUKS2. No automatic OSTree conversion or manual partitioning is supported.

Recovery-key enrollment prints a new key on the local console: record it privately.
FIDO2 enrollment is optional and remains unqualified with the sealed command line;
keep the passphrase/recovery key. The installer never passes machine-specific
`--karg` options to the sealed UKI.

After bootc finalizes the root and boot filesystems, the installer reopens the
encrypted backing filesystem for scratch cleanup and persistent configuration.
`bootc install mount --sysroot ... --latest ...` exposes the read-only composefs
deployment and its writable `/etc` and `/var`. The installer records the GPT
partition UUIDs in the new `/etc/fstab` for `/efi` and read-only `/boot`. The
initrd discovers the encrypted root through its GPT type. The EFI updater reads its signed
payload and certificate, stores its journal in that deployment's persistent
`/var/lib/finite/efi-updates`, and enables maintained fallback files in
`/etc/finite/bootloader.json`. The installer remounts the backing filesystem
read-only after releasing the deployment. Offline mode requires the native-media
kernel argument, a mounted native deployment and explicit ESP and state paths.
The ordinary runtime guard still requires a strict native composefs boot.

On first boot, complete the queued MokManager enrollment using the one-time
password entered on the installer console. Retain the production boot certificate
and existing module-signing certificate. Missing enrollment prevents shim from
starting the signed systemd-boot loader.

If a step fails, leave the console open and inspect `findmnt`, `lsblk` and the
printed failing step. The prototype does not automatically unwind partial mounts,
close LUKS, retry partitioning or reboot. Scratch may remain mounted at
`/var/tmp` and `/run/finite-install/target/.finite-install-scratch`; the deployment
may remain at `/run/finite-install/deployment`. Release only mounts and mappings
created by this run before attempting another fresh installation. Preserve an EFI
journal for inspection/recovery; do not erase it to bypass an interrupted update.

Before user-facing release, qualify actual ISO boot, encrypted root discovery,
MOK enrollment, first-boot account creation, real kernel/loader upgrade and
rollback, interruption cleanup and rescue recovery for both native profiles.
No working desktop account-creation flow is supplied by this prototype yet.
