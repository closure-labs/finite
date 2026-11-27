# Native installer research

Research date: 2026-11-25 UTC. This is a time-boxed source review. No installer,
ISO, VM or Nix build was run. It decides whether an existing installer can
produce the native bootc system that the unmerged native-bootc work qualified in
a VM. The existing OSTree images and their Anaconda ISOs are out of scope and
stay as they are.

**Recommendation: build a small custom installer.** Neither Anaconda's
kickstart path nor bootc-image-builder's `anaconda-iso` can produce the target
system today. Upstream has not published a timeline that would change this. The
deciding facts are in [Recommendation](#recommendation).

## Target system

The installer must reproduce what `scripts/vm-composefs/install-xbootldr.sh`
does at commit `89b94de` (not on `main`), with LUKS2 added for real installs:

- `bootc install to-filesystem --composefs-backend --bootloader systemd`, run
  by the pinned bootc runtime. `sources/bootc-runtime.json` at `89b94de` pins
  upstream commit `8275daa9227f`, the merge of
  [bootc PR #2573](https://github.com/bootc-dev/bootc/pull/2573), still labelled
  1.17.4.
- GPT with a 600 MiB ESP, a 4 GiB VFAT XBOOTLDR
  (`BC13C2FF-59E6-4262-A352-B275FD6F7172`), and a discoverable x86-64 root
  partition (`4F68BCE3-…`) whose filesystem supports fs-verity.
- LUKS2 on the root partition; the workstation unlocks it with FIDO2.
- Fedora shim, then locally signed systemd-boot installed as `grubx64.efi`,
  then a signed UKI. Trust comes from an enrolled MOK, not custom db keys.

Two properties of the sealed build constrain every installer:

1. The signed UKI's command line is fixed at build time. `seal-native.py` at
   `89b94de` builds it from the image's `kargs.d` plus
   `composefs.digest=…`. The image contributes only `rw`. There is no `root=`
   and no `rd.luks.*`. The initramfs must find and unlock the root through
   [discoverable partitions](https://uapi-group.org/specifications/specs/discoverable_partitions_specification/)
   (systemd-gpt-auto-generator). Per-machine kernel arguments are impossible.
2. The UKI requires fs-verity (`composefs.digest=` has no `?` marker). bootc
   refuses a strict install onto ext4 created without `-O verity`; Btrfs
   supports fs-verity natively.

## Sources reviewed

| Project | Revision read | Notes |
| --- | --- | --- |
| Anaconda | `main` at [`8f123da`](https://github.com/rhinstaller/anaconda/tree/8f123da05ee8e8936b201265ade18a15c267f2ac) (2026-11-25), tag `anaconda-44.35`, branch `fedora-45` | The bootc payload code is the same in all three |
| pykickstart | `master` at [`1568c86`](https://github.com/pykickstart/pykickstart/tree/1568c860e987b73959b10d023e60316649045ab3), version 3.78 | Anaconda's spec requires 3.77 or later |
| bootc | `main` at [`b88f28b`](https://github.com/bootc-dev/bootc/tree/b88f28b6586efd53457f5ceeee07bd1e42818eb3) (1.17.5); release [v1.17.5](https://github.com/bootc-dev/bootc/releases/tag/v1.17.5), 2026-11-20 | |
| image-builder (includes bootc-image-builder) | `main` at [`c42c259`](https://github.com/osbuild/image-builder/tree/c42c259ea3be5ee02c97489e3fdc629d7625dc08); latest release v91.0.0 | `osbuild/images` now redirects here |
| bootc-image-builder container | [`osbuild/bootc-image-builder`](https://github.com/osbuild/bootc-image-builder) | Now only a Containerfile; sources moved to image-builder |
| build-container-installer | `bed71f8` (v1.5.0, today's ISO input) | MOK enrollment comparison |

## 1. Anaconda kickstart

Anaconda has two container payloads. The older `ostreecontainer` command runs
`ostree container image deploy`
([`DeployOSTreeTask`](https://github.com/rhinstaller/anaconda/blob/8f123da05ee8e8936b201265ade18a15c267f2ac/pyanaconda/modules/payloads/payload/rpm_ostree/installation.py#L902-L991)).
It is OSTree-only. The bootloader comes from bootupd (GRUB and shim). It cannot
produce a composefs-native system.

The newer `bootc` command
([Anaconda PR #6298](https://github.com/rhinstaller/anaconda/pull/6298), merged
2026-02-10; [Fedora Magazine introduction](https://fedoramagazine.org/introducing-the-new-bootc-kickstart-command-in-anaconda/))
runs `bootc install to-filesystem`. It fails the target on every axis:

- **Bootloader is hardcoded to GRUB.**
  [`DeployBootcTask`](https://github.com/rhinstaller/anaconda/blob/8f123da05ee8e8936b201265ade18a15c267f2ac/pyanaconda/modules/payloads/payload/rpm_ostree/installation.py#L857-L862)
  always appends `--bootloader=grub` except on s390x. The same line exists at
  `anaconda-44.35` and on `fedora-45`.
- **The composefs backend is never requested.** No Anaconda source mentions
  `composefs-backend`. With `--source-imgref`, bootc selects the backend from
  the root it runs in, which is the installer, not the payload
  ([`prepare_install`](https://github.com/bootc-dev/bootc/blob/b88f28b6586efd53457f5ceeee07bd1e42818eb3/crates/lib/src/install.rs#L1726-L1761),
  [backend default](https://github.com/bootc-dev/bootc/blob/b88f28b6586efd53457f5ceeee07bd1e42818eb3/crates/lib/src/install.rs#L1835-L1860),
  [documented rule](https://github.com/bootc-dev/bootc/blob/b88f28b6586efd53457f5ceeee07bd1e42818eb3/docs/src/bootc-installation.7.md#the-storage-backend)).
  Anaconda also writes `/etc/ostree/prepare-root.conf` into the installer root
  as a workaround, which forces the OSTree default.
- **Post-install steps assume OSTree.**
  [`SetSystemRootTask`](https://github.com/rhinstaller/anaconda/blob/8f123da05ee8e8936b201265ade18a15c267f2ac/pyanaconda/modules/payloads/payload/rpm_ostree/installation.py#L1128-L1148)
  raises "Failed to find OSTree deployment" when none exists.
  [`FinalizeBootcTask`](https://github.com/rhinstaller/anaconda/blob/8f123da05ee8e8936b201265ade18a15c267f2ac/pyanaconda/modules/payloads/payload/rpm_ostree/installation.py#L1101-L1125)
  silently skips non-OSTree roots. The bootc task list is in
  [`rpm_ostree.py`](https://github.com/rhinstaller/anaconda/blob/8f123da05ee8e8936b201265ade18a15c267f2ac/pyanaconda/modules/payloads/payload/rpm_ostree/rpm_ostree.py#L115-L140).
- **Kernel arguments conflict with sealed UKIs.**
  [`CollectBootcKernelArgumentsTask`](https://github.com/rhinstaller/anaconda/blob/8f123da05ee8e8936b201265ade18a15c267f2ac/pyanaconda/modules/payloads/payload/rpm_ostree/installation.py#L720-L736)
  collects storage and LUKS arguments such as `rd.luks.uuid=`.
  [`DeployBootcTask`](https://github.com/rhinstaller/anaconda/blob/8f123da05ee8e8936b201265ade18a15c267f2ac/pyanaconda/modules/payloads/payload/rpm_ostree/installation.py#L864-L869)
  passes each one as `--karg`. For a prebuilt UKI, bootc
  [refuses any `--karg`](https://github.com/bootc-dev/bootc/blob/b88f28b6586efd53457f5ceeee07bd1e42818eb3/crates/lib/src/install.rs#L804-L817)
  ("Cannot use externally specified kernel arguments with a prebuilt boot
  image"). This design depends on kernel arguments the sealed image cannot
  accept.
- **No XBOOTLDR.** Neither Anaconda nor pykickstart mentions XBOOTLDR. The
  kickstart `part` command has no partition-type option, so a VFAT partition
  with the XBOOTLDR GUID cannot be requested.
- **ext4 lacks fs-verity.** Anaconda's ext4 does not use `-O verity`, so a
  strict composefs install onto it fails
  ([bootc docs](https://github.com/bootc-dev/bootc/blob/b88f28b6586efd53457f5ceeee07bd1e42818eb3/docs/src/bootc-installation.7.md#composefs-backend)).
  Btrfs would avoid this, but it does not fix anything else on this list.

LUKS2 with a passphrase works through `--encrypted --luks-version=luks2`.
pykickstart has no FIDO2 or TPM2 enrollment option. bootc's
[encryption guidance](https://github.com/bootc-dev/bootc/blob/b88f28b6586efd53457f5ceeee07bd1e42818eb3/docs/src/bootc-filesystem-encryption.7.md#recommendation-handle-root-filesystem-encryption-independently-of-bootc)
suggests a `%post` `systemd-cryptenroll`. Anaconda's unlock still relies on
its collected kernel arguments, which the sealed UKI cannot carry.

Anaconda's systemd-boot support (`bootloader --sdboot`) applies only to package
installs: rpm-ostree payloads skip Anaconda's own bootloader installation
([`installation.py`](https://github.com/rhinstaller/anaconda/blob/8f123da05ee8e8936b201265ade18a15c267f2ac/pyanaconda/modules/storage/bootloader/installation.py#L101-L103)).
[Bug 2418280](https://bugzilla.redhat.com/show_bug.cgi?id=2418280) reported
that `--sdboot` was ignored in Fedora 43; it was closed as a duplicate.

**Syntax exists, implementation does not.** pykickstart added
[`F45_Bootc`](https://github.com/pykickstart/pykickstart/blob/1568c860e987b73959b10d023e60316649045ab3/pykickstart/commands/bootc.py#L105-L139)
with `--bootloader none|grub|systemd` and `--composefs` on 2026-04-20 (commit
`f2f44dca7cd7`). The
[Fedora 45 handler](https://github.com/pykickstart/pykickstart/blob/1568c860e987b73959b10d023e60316649045ab3/pykickstart/handlers/f45.py#L33)
uses it; the
[Fedora 44 handler](https://github.com/pykickstart/pykickstart/blob/1568c860e987b73959b10d023e60316649045ab3/pykickstart/handlers/f44.py#L33)
does not. No Anaconda code reads either attribute. A search of Anaconda pull
requests and issues for composefs, systemd-boot and XBOOTLDR found no open
work. Recent bootc work in Anaconda covers mount points, rescue mode, fstab and
`bootc install finalize`.

## 2. bootc-image-builder

bootc-image-builder's sources moved into
[`osbuild/image-builder`](https://github.com/osbuild/image-builder). The
[`osbuild/bootc-image-builder`](https://github.com/osbuild/bootc-image-builder)
repository now only builds a container that links `bootc-image-builder` to
`image-builder`.

- **`anaconda-iso` is the `ostreecontainer` path.**
  [`bootcInstallerKickstartStages`](https://github.com/osbuild/image-builder/blob/c42c259ea3be5ee02c97489e3fdc629d7625dc08/pkg/manifest/anaconda_installer_iso_tree.go#L669-L700)
  writes an `ostreecontainer` kickstart with an `oci` transport, plus a `%post`
  running `bootc switch --mutate-in-place`. User kickstart content is included
  after that. The result is an OSTree-backend system with bootupd/GRUB.
  Composefs-native, systemd-boot and XBOOTLDR are not reachable through
  blueprint or kickstart customizations.
- **`anaconda-iso` is legacy.** The
  [migration guide](https://github.com/osbuild/image-builder/blob/c42c259ea3be5ee02c97489e3fdc629d7625dc08/doc/20-advanced/20-bootc/50-migration.md#L90-L94)
  says image-builder does not support it and recommends `generic-iso`. The
  [legacy ISO page](https://github.com/osbuild/image-builder/blob/c42c259ea3be5ee02c97489e3fdc629d7625dc08/doc/20-advanced/20-bootc/20-legacy-isos.md)
  says it is still maintained.
- **Disk images do handle UKIs.** For a UKI image, image-builder's raw/qcow2
  pipeline
  [forces composefs and drops custom kernel arguments](https://github.com/osbuild/image-builder/blob/c42c259ea3be5ee02c97489e3fdc629d7625dc08/pkg/manifest/raw_bootc.go#L184-L195).
  It can pass a bootloader, and its partition tables know the
  [XBOOTLDR type](https://github.com/osbuild/image-builder/blob/c42c259ea3be5ee02c97489e3fdc629d7625dc08/pkg/disk/disk.go#L58).
  It produces preinstalled disk images, not an installer, and has no
  per-machine LUKS2/FIDO2 setup. It is not a fit for workstation installation.
- **`generic-iso` is a useful packaging tool.**
  [`generic-iso`](https://github.com/osbuild/image-builder/blob/c42c259ea3be5ee02c97489e3fdc629d7625dc08/doc/20-advanced/20-bootc/10-isos.md#generic-iso)
  turns any bootable container into a squashfs live ISO. On x86_64 it
  [boots through shim and GRUB](https://github.com/osbuild/image-builder/blob/c42c259ea3be5ee02c97489e3fdc629d7625dc08/data/distrodefs/bootc-generic/imagetypes.yaml#L212-L233)
  taken from the container. `--bootc-installer-payload-ref` embeds a payload
  in the live environment's container storage. The documented Anaconda
  examples on this page still use the same Anaconda `bootc` command described
  above.

## 3. Shim, MOK and Secure Boot

| Installer | Bootloader installation | Runs `bootc install`? | MOK handling |
| --- | --- | --- | --- |
| Anaconda `ostreecontainer` | bootupd installs shim and GRUB; Anaconda skips its own bootloader ([installation.py](https://github.com/rhinstaller/anaconda/blob/8f123da05ee8e8936b201265ade18a15c267f2ac/pyanaconda/modules/storage/bootloader/installation.py#L202-L203)) | No; `ostree container image deploy` | None |
| Anaconda `bootc` | `bootc --bootloader=grub` (bootupd) | Yes, `to-filesystem` | None |
| bootc-image-builder `anaconda-iso` | Same as `ostreecontainer` | No | None |
| Today's ISO (build-container-installer v1.5.0) | Same as `ostreecontainer` | No | `%post` runs `mokutil --import` of `sb_pubkey.der` with a fixed enrollment password and ignores failures |

None of them knows Finite's chain: shim, signed systemd-boot as `grubx64.efi`,
and a signed UKI. With `--bootloader systemd`, bootc runs `bootctl`, which
installs systemd-boot directly. The VM qualification booted that way using a
firmware db certificate. The shim/MOK chain was added per VM by
`configure-finite.py`. In the native design, `finite-efi-update.service` owns
`EFI/finite/{shimx64,mmx64,grubx64}.efi` and, when enabled, the fallback path
(`docs/efi-updates.md` at `89b94de`). Any installer must therefore stage that
chain, create the firmware entry, and queue MOK enrollment itself. Today's ISO
already makes users complete MokManager enrollment on first boot, so the
interaction is not new.

Fedora's own direction does not point to systemd-boot. For Fedora 45, FESCo
accepted a UEFI-only slim GRUB for sealed bootc images and rejected systemd-boot
([LWN, 2026-07-29](https://lwn.net/Articles/1085609/)). The
[officially signed systemd-boot](https://fedoraproject.org/wiki/Changes/OfficiallySignedSystemdBoot)
change page is an empty template with no target release.

## 4. Upstream status and timelines

| Item | State on 2026-11-25 |
| --- | --- |
| pykickstart `bootc --composefs --bootloader` | Merged 2026-04-20 for the F45 handler |
| Anaconda consuming those options | Not implemented on `main` or `fedora-45`; no pull request or issue found |
| Anaconda XBOOTLDR or sealed-UKI support (no `--karg`) | No upstream work found |
| bootc XBOOTLDR for composefs and systemd-boot ([PR #2573](https://github.com/bootc-dev/bootc/pull/2573)) | Merged 2026-11-11; included in [v1.17.5](https://github.com/bootc-dev/bootc/releases/tag/v1.17.5) (2026-11-20) |
| bootc install configuration kargs ignored with composefs ([#2539](https://github.com/bootc-dev/bootc/issues/2539)) | Open; irrelevant for sealed UKIs, which accept no kargs |
| bootc `tpm2-luks` extensions ([#476](https://github.com/bootc-dev/bootc/issues/476), [#477](https://github.com/bootc-dev/bootc/issues/477), [#1329](https://github.com/bootc-dev/bootc/issues/1329)) | Open; upstream advises doing encryption outside bootc |
| bootc-image-builder `anaconda-iso` | Legacy; image-builder offers `generic-iso` instead |
| Fedora boot.iso built by image-builder ([ModernizeBootISO](https://fedoraproject.org/wiki/Changes/ModernizeBootISO)) | Accepted for Fedora 46; only the ISO build changes, not Anaconda's payload |
| Fedora sealed-image bootloader | Slim GRUB, Fedora 45 |

No source gives a date for Anaconda composefs or systemd-boot support. Even
when the F45 kickstart options are implemented, three gaps would remain: the
`--karg` collision with sealed UKIs, the missing XBOOTLDR partition type, and
the Finite shim chain. Planning should not depend on Anaconda support arriving
in 2027.

`bootc install to-disk` is not an alternative. Its only encryption option,
[`--block-setup tpm2-luks`](https://github.com/bootc-dev/bootc/blob/b88f28b6586efd53457f5ceeee07bd1e42818eb3/crates/lib/src/install/baseline.rs#L1185-L1216),
wipes all passphrase slots, binds to the TPM only, and adds `luks.uuid=`
kernel arguments, which a sealed UKI rejects. The bootc docs call `to-disk`
mainly a demonstration of `to-filesystem`.

## 5. Custom installer shape

The smallest installer that fits is a hardened version of
`install-xbootldr.sh` in a live ISO.

**Media.** Build an installer container `FROM` the exact signed
`finite-native` image digest and add only live-boot needs: `dracut-live`, and
a shim/GRUB cdboot loader for the ISO itself. Package it with image-builder
`generic-iso` on the existing hosted ISO runner. Deriving from the payload
image means the installer runs the identical pinned bootc RPM, which
`docs/bootc-runtime.md` at `89b94de` requires. Embed the payload with
`--bootc-installer-payload-ref`, or as an OCI archive whose digest is recorded
in the ISO's `installation.json`. Verify the Cosign signature at ISO build
time, as `iso.sh` does today.

**Installer steps.** A text-mode script started by a systemd unit:

1. Refuse to run unless booted in UEFI mode. Report the Secure Boot state.
   Require the bootc version and payload digest to match the recorded pins.
2. List whole disks by `/dev/disk/by-id`. Exclude the boot medium and mounted
   devices. Require a minimum size (64 GiB based on the VM findings) and a
   typed confirmation of the disk identifier. Whole-disk installation only.
3. Partition with `sfdisk`: 600 MiB ESP, 4 GiB XBOOTLDR, and the rest as the
   discoverable x86-64 root type, so systemd-gpt-auto-generator can find and
   unlock it without kernel arguments.
4. Run `cryptsetup luksFormat --type luks2` on the root partition with an
   interactive passphrase, kept as the recovery keyslot. Optionally add
   `systemd-cryptenroll --fido2-device=auto` and `--recovery-key`.
5. Create Btrfs (to match the workstation) or `mkfs.ext4 -O verity` on the
   opened mapping, plus FAT32 on the ESP and XBOOTLDR. Mount them at the
   target's `/`, `/efi` and `/boot`.
6. Redirect bootc's temporary space to the target disk. bootc unpacks OCI
   archives into `/var/tmp`, which is RAM-backed on a live ISO; the full image
   needed about 18 GiB in the VM.
7. Run `bootc install to-filesystem --composefs-backend --bootloader systemd`
   with `--source-imgref` pointing at the embedded payload and
   `--target-imgref ghcr.io/closure-labs/finite-native:<channel>`. Pass no
   `--karg`, and do not pass the VM-only `--skip-finalize`. Treat
   `--generic-image` carefully: it skips firmware boot entries, which step 8
   creates instead.
8. From the installed deployment (`bootc install mount`), run its own
   `/usr/libexec/finite/update-efi` to place shim, MokManager and the signed
   loader, with `manageFallback: true` in `/etc/finite/bootloader.json`.
   Create a firmware entry for `\EFI\finite\shimx64.efi` with `efibootmgr`.
9. Queue MOK enrollment of the production boot certificate and the existing
   akmods module-signing certificate. Unlike today's `%post`, fail on error
   and show the one-time password and the MokManager steps on screen.
10. Check placement as `install-xbootldr.sh` does: UKIs and entries on XBOOTLDR,
    none on the ESP. Then finalize, unmount, close LUKS, sync and reboot.

**Main risks.**

- *FIDO2 unlock with a sealed command line.* No per-machine `rd.luks.*` is
  possible. gpt-auto must attempt the enrolled FIDO2 token, or a generic
  option such as `rd.luks.options=fido2-device=auto` must be added to the
  image's `kargs.d` before sealing. This has not been tested, and the same
  constraint applies to any installer. It needs a VM test with an emulated
  FIDO2 device before hardware.
- *Destructive disk handling.* Choosing the wrong disk is the largest user
  risk. Mitigate with stable IDs, typed confirmation and refusing mounted or
  boot media, and qualify only in VMs with file-backed disks.
- *First-boot trust.* Until the MOK is enrolled, shim refuses the signed
  loader. A skipped MokManager screen leaves an unbootable install, so keep
  rescue media and document re-queuing enrollment.
- *Live-ISO Secure Boot.* The live kernel and GRUB must be signed by keys
  shim trusts. A Fedora-signed kernel works; any other kernel needs its MOK
  already enrolled.
- *Ownership.* Finite owns this code: bootc CLI changes, the bootc pin, and
  partitioning edge cases (4Kn disks, NVMe namespaces, existing RAID
  signatures). Mitigation: track bootc releases with the existing runtime
  updater, keep the script small, and qualify each release.
- *Scope gaps versus Anaconda.* No GUI, no dual-boot or manual partitioning,
  and no user creation unless the script adds a step or the native profiles
  provide a first-boot account flow; which applies is not yet checked. This is
  acceptable for a workstation-first OS, but must be stated in the
  installation guide.
- *Memory and runner limits.* Unpacking redirected to disk (step 6) avoids the
  live system's RAM limit. ISO builds stay on the hosted runner, never on the
  16 GiB workstation.

## Recommendation

**Custom installer.** Deciding facts:

1. Anaconda's `bootc` payload hardcodes `--bootloader=grub`, never selects
   composefs, and expects an OSTree deployment. This holds on Fedora 44, the
   `fedora-45` branch and `main`.
2. Anaconda passes its collected LUKS and storage arguments as `--karg`, which
   bootc rejects for prebuilt UKIs. Sealed images need argument-free root
   discovery, which Anaconda does not offer.
3. Neither Anaconda nor kickstart can create a VFAT XBOOTLDR partition.
4. bootc-image-builder's `anaconda-iso` is the OSTree `ostreecontainer` path
   and is legacy in image-builder.
5. No existing installer installs Finite's shim, systemd-boot and MOK chain.
   Fedora's sealed-image direction is GRUB.
6. The F45 kickstart options are syntax only, with no Anaconda implementation
   or pull request. Even when implemented, points 2, 3 and 5 would remain.

The custom installer reuses the qualified `install-xbootldr.sh` sequence and
the image's own bootc runtime and EFI updater. image-builder `generic-iso` can
build the media. Revisit this if Anaconda implements `bootc --composefs
--bootloader systemd` with a no-`--karg` mode for UKIs and XBOOTLDR
partitioning.

## Follow-up notes

- bootc v1.17.5 (2026-11-20) contains the pinned XBOOTLDR commit (`8275daa` is
  an ancestor of tag commit `ff14fe2`). The native branch's daily
  `update-bootc-runtime.yml` should now propose moving off the 1.17.4
  snapshot.
- Today's OSTree ISO pipeline is described in
  [`iso.sh`](../scripts/bluebuild/iso.sh),
  [`prepare-installer.sh`](../scripts/bluebuild/prepare-installer.sh),
  [`files/installer/`](../files/installer/Containerfile) and
  [`iso.yml`](../.github/workflows/iso.yml). None of it is reusable for
  native media beyond the Cosign verification and provenance patterns.

## Continuation status

The installer prototypes in jj changes `pyvvsonm` and `pqvtovuo` were already
present when the 2026-11-25 continuation started. They are being hardened as the
custom-installer path described above. Native profiles now use distinct tags in
`ghcr.io/closure-labs/finite`; the OSTree profiles retain their tags. The
[continuation record](native-rollout-progress.md) distinguishes source tests
from the still-pending ISO, encrypted VM and hardware qualification.
