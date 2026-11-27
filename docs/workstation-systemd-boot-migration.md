# Workstation systemd-boot migration

The approved v0.9.0 native migration is tracked in the
[implementation and acceptance record](v0.9.0-implementation.md), including the
workstation recovery-backup commands and production prerequisites. The older
trial below remains a boot-chain experiment.

Status: trial successfully booted with Secure Boot enforcing. OS update/rollback
integration is still incomplete. New EFI files and a firmware entry exist; original BootOrder,
GRUB, rEFInd, partitions and host packages are preserved. Local bookmark:
`feat/systemd-boot-secure-boot`. No branch has been pushed.

Native composefs VM qualification passed for the Fedora fixture and the
configured Finite candidate, including upgrade, rollback, persistence, module
MOK trust and tamper rejection. Production build integration and workstation
migration remain incomplete. See
[the qualification report](systemd-boot-vm-qualification.md) for actual results,
build issues, evidence paths, and remaining hardware acceptance work.

## Staged trial (authorized)

The first trial keeps the OSTree backend. It wraps the running deployment's
existing kernel, initramfs and arguments in one locally signed UKI and prepares
a signed systemd-boot binary for an isolated Fedora-shim chain. One such UKI
fits; the old deployments continue to use their existing files on ext4 `/boot`.
This tests the boot chain, not automatic OSTree/systemd-boot integration.
GRUB remains the normal boot path and must not be removed after this trial alone.

`scripts/workstation/prepare-boot-trial.py` is the privileged preparation step.
It checks the actual ESP PARTUUID and running BLS/deployment identity, rejects
queued deployments, backs up the ESP, and builds a bundle under root-only
`/var/lib/finite-boot-trial`. It uses a locally built tools container with no
network, host devices, or privileged-container access. The signing key stays
under that root-only directory; only its certificate belongs on the ESP.
It loads the tools image into root's Podman storage but does not install host
packages, write the ESP, enroll a key, change boot entries, or reboot.

The tools image is built from `scripts/workstation/Containerfile.boot-tools`,
which pins the Fedora base digest. Its installed package versions and resulting
image ID are recorded. Build scripts and tools are local; no registry push is
part of this workflow.

Preparation completed on 2026-11-16 (user log:
`/tmp/finite-boot-trial-preparation.tx`). UKI size: 262458816 bytes.
Deployment: `4aadad13bdc483c13917fd44330d9557cf7fa2a5ae0868a07b562044c58dd8ba.0`.
Certificate SHA256 fingerprint:
`7D:58:B1:F0:B2:1C:EF:DE:06:E1:C1:89:80:B7:3E:52:4F:F1:29:51:70:17:5E:FB:27:90:37:CD:62:B9:27:FA`.
Both locally signed files passed signature verification and contain SBAT.
The subsequent successful host trial is recorded below.

Run `sudo python3 scripts/workstation/inspect-boot-trial.py` to recheck
signatures, embedded UKI section bytes, current deployment and source files,
shim/MokManager identity, backup presence, and initramfs filenames that may
indicate private keys. This prints public evidence only. Filename screening is
an aid to review, not proof that an initramfs contains no secrets.

The real bundle inspection verified both signatures and the embedded input
bytes, and confirmed a 114995200-byte ESP backup. Its sole flagged path was
`etc/gshadow`. The inspector now privately checks its password fields and
accepts only empty fields or lock markers (`!`/`*`); even a locked password hash
still blocks staging. It prints counts and a boolean, never password fields.

`sudo python3 scripts/workstation/stage-boot-trial.py` reruns that inspection,
then copies only public EFI files and the enrollment certificate into the new
`EFI/finite-systemd` directory. It creates a BLS entry and `loader.conf` only
if those destination files do not already exist. It creates a firmware entry
with `efibootmgr --create-only` and verifies the original BootOrder and BootNext
are preserved. It does not queue enrollment or a boot. A root-only staging
journal records partial progress for review if any step fails; do not blindly
rerun after a partial failure. Unit tests cover refusal of existing trial
paths, creation without selecting the entry, and restoring BootOrder if
firmware inserts the new entry despite `--create-only`.

After preparation, inspect the signed bundle and initramfs contents before
copying anything onto the unencrypted ESP. The deployment/boot-link identity
must be rechecked at staging and immediately before the trial. An OSTree update
can rotate the `ostree=/ostree/boot.*` links; this is a temporary trial bundle,
not a durable recovery image or a safe default across future updates. Do not
queue an OS update between staging and the test boot.

Staging completed successfully (user log `/tmp/finite-boot-trial-staging.txt`).
`etc/gshadow` contained two entries and no password material. The new firmware
entry is `0002`, label `Finite systemd-boot trial`, loading
`\EFI\finite-systemd\shimx64.efi` on the current ESP. Original BootOrder is
`0007,0006,0004,0000,0005,0001`; it is unchanged and excludes the trial.

Next, queue the root-private bundle's public DER certificate with
`sudo mokutil --import /var/lib/finite-boot-trial/output/MOK.der`, choosing a
temporary enrollment password locally. After successful import, use
`sudo efibootmgr --bootnext 0006` for a one-time boot through the existing
Fedora shim to process enrollment. Keep Secure Boot off for this enrollment
reboot. In MokManager select Enroll MOK, inspect the certificate subject
`Finite workstation boot trial`, Continue, Yes, enter the temporary password,
and reboot back to Linux. Confirm with
`sudo mokutil --test-key /var/lib/finite-boot-trial/output/MOK.der` before
selecting entry `0002` or enabling Secure Boot for the trial. Full hardware
boot confirmation requires Secure Boot enabled, the expected UKI/deployment,
root unlock, and login. No cleanup/removal command is provided by these tools.

Enrollment was confirmed after reboot: the user's
`/tmp/finite-mok-enrollment.tx` reports that the exact bundle certificate is
already enrolled. Boot ID after enrollment is
`e66eedbf-d1c8-433c-8728-a8d1f4f0120f`; the workstation still reports GRUB and
Secure Boot disabled, with the same kernel command line and deployment target.

`sudo python3 scripts/workstation/arm-boot-trial.py` reruns inspection,
verifies the staged artifact hashes and configurations, confirms enrolled MOK
trust, and refuses a shim-validation bypass. It checks the exact trial firmware
entry and original BootOrder, refuses to replace another pending BootNext, and
records the pre-trial boot ID before selecting only BootNext. It never reboots.
After success, reboot into F2 setup, enable Secure Boot while preserving existing
firmware keys, save, and use F12 to select `Finite systemd-boot trial` if entering
setup consumed BootNext. If the trial fails, use F12 `Fedora` for the existing
shim/GRUB path. If that also fails with Secure Boot enabled, restore the prior
Secure Boot setting and boot Fedora; retain the exact failure message for review.

After the firmware change, the user reported a verification error in a MOK
screen and recovery to GRUB; the error code and attempted EFI entry are unknown.
Do not treat this as a confirmed failure of the staged systemd-boot chain.
Observed boot ID: `6fa5875e-a61e-4263-8372-5342d4b1e075`, BootCurrent `0006`
(Fedora), with original BootOrder unchanged and rEFInd first. EFI variables show
SecureBoot=1, SetupMode=0, AuditMode=0, DeployedMode=1. Kernel logs confirm EFI
Secure Boot lockdown and loading of the `Finite workstation boot trial` MOK.
Thus enforcement and MOK enrollment are confirmed on the GRUB recovery boot;
custom firmware keys are unnecessary for the intended shim/MOK chain.
Next trial: revalidate/rearm, reboot without further firmware changes, and
explicitly choose `Finite systemd-boot trial` in F12. Capture the exact error
if that specific entry fails; no additional certificate enrollment is indicated.

The subsequent arming attempt stopped before BootNext because installed mokutil
0.7.2 printed `is already enrolled` but exited 1 for `--test-key`. The enrollment
check now exports the public enrolled MOK certificates into a private temporary
directory and requires an exact DER byte match with the trial certificate.
Export failures and missing/different certificates still abort. A live read-only
export succeeded (exit 0, four certificates) and included the exact SHA256
fingerprint recorded above. No enrollment or firmware changes were made by
that check. Regression tests cover exact matching, wrong certificates, and
export failure. Rerun arming to select the trial after these checks.

## Successful hardware trial

The user confirmed successful boot into the trial. Read-only runtime checks
verified boot ID `173a0354-73fb-4a45-8d21-14b000c3c45a` (different from the
prior recovery boots), systemd-boot 259.10-1.fc44 at
`\EFI\finite-systemd\grubx64.efi`, selected entry `finite-trial.conf`, and
systemd-stub 259.10-1.fc44 at `\EFI\finite-systemd\finite-trial.efi`.
SecureBoot=1, SetupMode=0, AuditMode=0; bootctl reports Deployed Mode and a
measured UKI. Kernel lockdown is active in integrity mode. The signed trial
marker and the expected OSTree target and encrypted-root/FIDO2 arguments are
present on the running command line. Login/unlock success was reported by the
user; the specific unlock device was not independently tested.

`systemd-boot-preflight.py --trial` passed against the actual runtime. Public
evidence is retained in ignored local artifact
`artifacts/systemd-boot/successful-trial.json`, with this tracked summary for
persistence. The full migration check still flags OSTree update integration.

Firmware BootOrder remains `0007,0006,0004,0000,0005,0001`, excluding the trial.
BootCurrent anomalously reports `0000` (HTTP boot); it does not match the
observed loader/stub paths. That discrepancy is unexplained and must not be
used to delete or rewrite a firmware entry. Actual loader/stub metadata and
the signed command-line marker establish that the trial ran.

The demonstrated chain needs Fedora shim and the enrolled MOK, with no rEFInd
in the demonstrated loader path. GRUB has not been removed and the trial has
not been made the default: its `ostree=/ostree/boot.0/...` argument is tied to
the current deployment and can become stale on updates. Next implementation
work is durable signed-UKI generation and selection across image upgrades and
rollbacks (or a separately staged native composefs system), plus sufficient
storage for current/staged/rollback images. Retiring GRUB before that work
would remove the existing supported update and recovery path.

## Update integration and Windows cleanup follow-up

The user authorized continuing the update integration and removing Windows boot
leftovers. That includes `EFI/Microsoft` and firmware entries pointing there;
it does not include Microsoft UEFI trust certificates, which validate shim.
No Windows cleanup is confirmed yet; it requires the root command below.

Installed `ostree-finalize-staged.service` runs finalization in **ExecStop at
shutdown**, not a startup ExecStart. A synchronizer that only runs at boot
would miss the first boot of a new deployment. The sysroot already has
`bootloader=none` for the existing static GRUB/BLS arrangement. No setting was
changed. The [upstream translation-layer issue](https://github.com/bootc-dev/bootc/issues/2098)
remains open; production update integration is not supplied by the trial.

Partition-sector inspection shows p1 starts at 2048 and ends at 1230848, p7
starts there and ends at 5425152, and p8 starts there and ends at 1000214528.
The disk ends at 1000215216. Thus there is no useful unallocated gap for a new
boot partition. No partition modification has been performed.

Next command:

```bash
sudo python3 scripts/workstation/measure-boot-storage.py --remove-windows-efi
```

It refuses cleanup if lsblk reports a Windows filesystem or Microsoft
data/reserved/recovery partition. It backs up `EFI/Microsoft` to root-private
`/var/lib/finite-boot-trial/windows-efi-before.tar`, verifies every backed-up file
hash, and removes only that directory and firmware entries targeting it.
It writes a separate cleanup result before starting the measurements.

Measurement uses dracut skipcpio to preserve the exact early-microcode prefix,
decompresses the remaining archive in private temporary storage, and recompresses
with XZ/CRC32. SHA256 of the decompressed bytes must remain identical. Only
reports remain; the original initramfs, running UKI and trial ESP files are
unchanged. The current kernel has `CONFIG_RD_XZ=y`. The size report budgets
current+rollback+one replacement image and 64 MiB reserve, allowing eventual
retirement of only the old trial UKI after a compact replacement has booted.
The results decide whether the existing ESP is viable; estimates are not
installation or boot qualification. Upgrades/rollback and failure handling
must be tested before changing the default loader or removing GRUB.

Windows cleanup completed: the user-run command reported removal of
`/boot/efi/EFI/Microsoft`, no matching firmware entries, and a verified backup
of all 146 files at `/var/lib/finite-boot-trial/windows-efi-before.tar`.
Firmware trust certificates were preserved. Both initramfs compression
measurements subsequently completed. Lossless XZ recompression reduced each
initramfs by only about 6.3 MiB. Estimated UKI sizes are 256765556 and 256767296
bytes. After Windows cleanup the ESP has 281300992 bytes free; the existing
trial UKI occupies 262458816 bytes. After eventual retirement of that original
trial and a 64 MiB reserve, the usable image budget is 476650944 bytes. Even
two estimated compact UKIs total 513532852 bytes, exceeding that budget;
three require 770300148 bytes. Recompression alone does not provide adequate
headroom. No original initramfs or bootable UKI was replaced by measurement.

### Upstream architecture preference

The user asked for Fedora Silverblue's established practice. Its OSTree boot
path is Fedora shim plus GRUB reading OSTree's BLS entries, with bootupd handling
bootloader components separately. A custom signed-UKI synchronization bridge
would be new boot infrastructure to maintain, rather than Silverblue practice.
It has not been installed and should not be the default recommendation.

For the requested systemd-boot branch, prefer bootc's supported native composefs
backend plus signed UKIs and systemd-boot. Validate a candidate image and its
upgrade/rollback behavior in a disposable VM, then prepare a parallel migration
with sufficient FAT boot storage. Retain the working installation throughout
qualification. This is distinct from OSTree's `prepare-root.conf` composefs
mount option. Source:
https://bootc.dev/bootc/bootc-bootloaders.7.html.
The bridge transaction below is research only, not an implementation commitment.

### Proposed OSTree bridge transaction (not installed)

Keep OSTree's POSIX `/boot` and BLS configuration. Do not change the existing
root filesystem, partition table, or bootc storage backend. The bridge must:

1. Serialize its own operations and take a consistent deployment snapshot after
   OSTree finalization. Handle `bootc rollback` and karg changes as well as upgrades.
2. Create stable, root-owned deployment symlinks outside OSTree's rotating boot
   slots, using a private mount namespace if sysroot writes are needed. Pin the
   referenced deployments through OSTree before publishing a signed image.
   Track only bridge-created pins and never remove a user-created pin.
3. Sign each UKI's stable target, kernel, initramfs and full machine arguments.
   Build and verify in private root storage before changing the ESP. Reusing a
   cached image requires an exact match of all inputs and the signing certificate.
4. Retain the currently booted, verified image and its deployment if signing,
   storage, finalization or ESP copy fails. A failed sync must leave a bootable
   default even if OSTree already rotated its normal boot links.
5. Publish a new entry/default only after its complete image has been copied,
   flushed and verified. Treat persistent systemd-boot default EFI variables as
   part of this transaction; `loader.conf` alone can be overridden by them.
6. Remove only bridge-owned stale entries/images/pins after publication. Avoid
   touching existing GRUB files, other EFI loaders or the original trial during
   initial qualification.

Three full images allow a conservative copy-before-prune transaction. If only
two fit, a separate two-slot design is possible: sign and verify the candidate
off-ESP, retire only the older nonbooted rollback image, and copy the candidate
while retaining the booted image and pinned deployment. A power loss must still
leave that booted image usable. This gives up the *older* rollback during the
copy, while the last working system remains the new candidate's rollback. That
policy needs explicit failure tests; the three-image storage estimate alone
must not be treated as proof that repartitioning is necessary.

Upstream initramfs target handling accepts an `ostree=` symlink and resolves
it to the deployment root. OSTree userspace discovers its booted deployment by
device/inode while parsing its own standard BLS entries. These source facts
suggest a stable-link bridge is possible, but do not establish compatibility
on this host. Verify the installed version, Secure Boot, bootc status, garbage
collection, SELinux, shutdown ordering, key access, upgrades, rollback, and
failure/power-loss cases in a disposable VM before activating the hook.

## Inspected workstation (2026-11-16)

- Dell XPS 13 9350, Finite 44.20261111.1, systemd 259.10, bootc 1.17.1.
- Running loader: GRUB 2.12; Secure Boot disabled.
- Current deployment is OSTree (`ostree=` on the kernel command line).
  `/usr/lib/ostree/prepare-root.conf` enabling composefs does **not** mean this
  is bootc's native composefs backend.
- ESP: `/dev/nvme0n1p1`, mounted at `/boot/efi`, FAT32, PARTUUID
  `5bc0db94-2336-4824-b55c-1c6d8395221b`, about 489 MiB available.
- `/boot`: `/dev/nvme0n1p7`, ext4. Root: LUKS-encrypted btrfs on p8,
  with FIDO2 unlock arguments that must survive migration.
- Each of the two installed kernel/initramfs pairs occupies about 252 MiB.
  Two corresponding UKIs plus staging headroom cannot fit in the available ESP.
- Firmware entries include Fedora shim, rEFInd via `EFI/refind/shimx64.efi`,
  and a systemd-boot entry referencing a different PARTUUID
  (`bf68e830-38b9-48be-b87e-6f527ee7c0fa`). Do not reuse that old entry blindly.
- systemd-boot EFI binaries, ukify, and sbsigntools are not installed.
- User-supplied root inspection in `/tmp/finite-boot-inspection.txt` confirms
  `BootCurrent: 0007` (rEFInd's shim), with GRUB reporting as the current loader.
  rEFInd is part of the current boot path, not merely an unused menu entry.
- ESP contents include Fedora shim/GRUB/MokManager, rEFInd's copies, and
  Microsoft boot files. No Windows root partition appears in `lsblk`; the
  Microsoft files alone do not establish a working Windows installation.
- `bootupctl status` reports EFI grub2 2.12-66.fc44 and shim 16.1-7 current.
  `bootc status` explicitly reports `store: ostreeContainer`, `composefs: null`,
  no staged deployment, and a rollback deployment of 44.20261103.
- The root inspection confirms a 600 MiB ESP, 2 GiB ext4 `/boot`, and 474.4 GiB
  LUKS partition. Enrolled signing keys still need inspection. Installation
  requires commands run through the user's authenticated terminal.

## Required design decisions

[bootc's bootloader documentation](https://bootc.dev/bootc/bootc-bootloaders.7.html)
supports systemd-boot only with its native composefs backend, not OSTree.
Changing the loader alone does not migrate deployment management. A supported
native composefs installation or a separately engineered and tested OSTree
integration is required. Do not run `bootc install to-disk` on this workstation:
it is a destructive installer, not an in-place bootloader conversion.

The [upstream migration tracker](https://github.com/bootc-dev/bootc/issues/2079)
remains open; recent linked changes explicitly reject installing the composefs
backend on an existing OSTree system. `to-existing-root` is not a safe shortcut:
its [manual](https://bootc.dev/bootc/man/bootc-install-to-existing-root.8.html)
says it wipes the existing `/boot`. That would violate the requirement to keep
the existing GRUB recovery path until the replacement has booted successfully.
Choose between a separately tested custom in-place integration and a backed-up
native composefs reinstall/parallel installation before providing host mutation
commands. A spare disk can preserve the original installation during testing.

Use a larger ESP or a VFAT XBOOTLDR partition for current, staged, and rollback
UKIs, with room for atomic replacement. The existing ext4 `/boot` is not that
partition. No resize/reformat is authorized by this preparation. Alternatively,
measure whether a smaller initramfs retaining encrypted-root/FIDO2 and hardware
support makes the existing ESP viable before changing partitions.

The intended trust chain is firmware → Fedora shim → locally signed
systemd-boot → signed UKI containing kernel, initramfs and command line.
Use an isolated directory such as `EFI/finite-systemd/`, retaining the original
Fedora directory and fallback loader. Shim commonly expects `grubx64.efi` as its
next-stage filename; a signed systemd-boot binary at that name is not GRUB.
Confirm compatible shim/SBAT behavior and enrolled MOK trust before activation.
Keep private signing keys outside this repository and the ESP. Do not reset
firmware keys or disable signature verification to make the test pass.

rEFInd is optional. It provides a graphical chooser and discovery of other OS
loaders; systemd-boot and the firmware menu can cover the observed Linux setup.
Microsoft boot files also exist, though no Windows root partition was found.
rEFInd can chainload a shim, and its existing firmware entry
already loads one. That fact does not prove the complete chain works with
Secure Boot enabled. See [rEFInd's Secure Boot documentation](https://www.rodsbooks.com/refind/secureboot.html)
and [systemd's boot components](https://systemd.io/ROOTFS_DISCOVERY/).

## Resume and acceptance

1. Obtain root-capable access; inspect ESP files, `efibootmgr -v`, MOKs,
   `bootupctl status`, and `bootc status`. Back up ESP, firmware entry listing,
   partition table and recovery material before boot changes.
2. Resolve the backend and storage design above. The optional recipe module
   `recipes/shared/systemd-boot-tools.yml` supplies preparation tools; it is not
   enabled in production recipes and does not itself enable Secure Boot.
3. Build and test the candidate in a Secure Boot VM, including image upgrade,
   rollback, signed UKI regeneration and loader/shim updates. Preserve upstream
   kernel/module signatures and encrypted-root/FIDO2 support.
4. Stage the verified signed loader and UKIs alongside GRUB. Record artifact
   hashes, deployment identity and pre-test boot ID. Enroll the public key via
   MOK Manager if needed, with physical confirmation, then enable Secure Boot.
5. Create a separate firmware entry on the actual ESP and use BootNext for the
   first trial. Keep the normal boot order and recovery paths intact.
6. After reboot, run `python3 scripts/workstation/systemd-boot-preflight.py`
   outside the agent sandbox (which may hide EFI variables). Require a new boot
   ID, systemd-boot as current loader, Secure Boot in user mode, the expected
   signed UKI/deployment, successful root unlock and desktop login. Verify
   updates and rollback before retiring their existing mechanism.
7. Only after that evidence, make systemd-boot the default and review exact
   GRUB-owned files/packages for removal. Preserve shim/MokManager when used by
   the new chain. Do not recursively remove `EFI/fedora`, `EFI/BOOT`, or rEFInd
   merely because GRUB booted from there previously. A shim executable alone
   is not a tested recovery path.

The preflight command is read-only and fails closed when evidence is absent.
It never removes GRUB, changes boot order, or claims a successful reboot.
