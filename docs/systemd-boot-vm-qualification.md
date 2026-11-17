# Native systemd-boot VM qualification

Run date: 2026-11-17. This is a disposable native bootc composefs experiment on
`feat/systemd-boot-secure-boot`. It does not convert the workstation's OSTree
installation or qualify removing its recovery bootloader.

## Results

| Check | Fedora bootc fixture | Configured Finite VM |
| --- | --- | --- |
| Fresh native composefs installation | Pass | Pass |
| Signed systemd-boot and UKI, Secure Boot user mode | Pass | Pass |
| Required fs-verity, kernel lockdown, SELinux enforcing | Pass | Pass |
| Zero failed systemd services | Pass | Pass after VM configuration |
| Existing signed ZFS/v4l2loopback modules trusted through MOK | Not applicable | Pass after VM configuration |
| Switch to independently sealed update and reboot | Pass | Pass |
| Roll back and reboot | Pass | Pass |
| Preserve modified `/etc` and `/var` files through both | Pass | Pass |
| Reject a modified signed UKI before kernel startup | Pass | Pass |

Both runs use bootc 1.17.1 and systemd 259.10. The Fedora fixture uses kernel
7.3.3-200.fc44; the Finite candidate uses 7.2.11-200.fc44. The full Finite run's
successful update, rollback, and negative test finished at 07:52 UTC.

The negative test clones the stopped VM's disk and firmware variables, verifies
the original signature, changes one byte of the embedded composefs digest,
requires signature verification to fail, and boots the clone. systemd-boot
reports `Error loading EFI binary …: Access denied`; no kernel starts. This is
an explicit loader rejection, not an inference from SSH timing out.

## Inputs and retained evidence

The Fedora base is pinned to
`quay.io/fedora/fedora-bootc@sha256:f8170dc0b8b3b48c14d0b52ee51b926642a377414757af581cd9dc0cbb8a0605`.
The Finite source is pinned to
`ghcr.io/closure-labs/finite@sha256:60a46916d22e4a7c33c625aff8f963b19a9a2e18207b1662192d3a199585ddb4`.
Its keyless signature was verified with the GitHub Actions issuer and this
repository's main-branch workflow identity before derivation. That verification
is separate from the workstation's existing older public-key container policy;
the host policy was not changed.

Local, ignored evidence directories:

- `artifacts/systemd-boot/vm-docker/qualification.json`: completed fixture phases.
- The same directory's `first-boot`, `updated`, and `rolled-back` evidence and
  bootc JSON files: loader, stub, Secure Boot, strict digest, native backend,
  SELinux, failed-unit listing, and revision identity.
- `updated-persistence.txt` and `rolled-back-persistence.txt`: `/etc` and `/var`
  sentinel contents after each transition.
- `tamper/result.json`, `signature-check.txt`, and `tampered-serial.log`: the
  controlled negative test.
- `artifacts/systemd-boot/vm-finite/`: the separately derived full-image run.
- Its `qualification.json`, `updated-module-trust.txt`, and
  `rolled-back-module-trust.txt`: successful transitions with the exact MOK,
  loaded ZFS/v4l2loopback modules and guarded OSTree-only units.
- `artifacts/systemd-boot/finite-current-keyless-signature.json`: source-image
  signature verification.

VM signing and SSH private keys remain in private ignored state directories.
Only VM certificates are added to file-backed OVMF variables. No workstation
MOK, firmware trust database, boot order, ESP, partitions or packages are changed
by these tests. All virtual block devices are ordinary files in the checkout.

## Build findings

The documented split-rootfs / separate UKI-tools-stage pattern produced a
digest mismatch with bootc 1.17.1 in both Docker and rootless Podman. Directory
metadata in the mounted build view differed from the canonical OCI-import view.
The installer rejected those images; verification was never disabled.

`scripts/vm-composefs/seal-oci.py` is a diagnostic workaround: import the OCI
archive with bootc's own importer, compute the bootable root digest, sign a UKI
with that digest, then re-import the completed archive and require the same
digest. The temporary metadata repository's insecure setting is confined to
build storage; the target's strict command line and status require fs-verity.
This uses an internal bootc interface and is not a production build solution.

The first installed fixture also exposed a missing `rw` kernel argument. GPT
auto-discovery mounted the physical root read-only, preventing persistent
`/etc` and `/var` initialization. The corrected signed UKIs include `rw`; the
composefs root itself remains read-only. The passing fixture run was a fresh
installation from the corrected archives, followed by upgrade and rollback.

The full-image bootstrap also required more temporary storage than the small
fixture: bootc unpacks OCI archives into `/var/tmp`. Its initial 3 GiB reserve
ran out before image import. The disposable bootstrap filesystem was expanded,
and the harness now reserves 18 GiB beyond the exported root filesystem. The
target was still 32 GiB at that point.

The full Finite upgrade then correctly refused insufficient working space after
unpacking its OCI archive; no deployment was staged. The stopped disposable
target was expanded from 32 to 64 GiB, retaining its existing partition UUIDs,
and its root partition/filesystem were grown. Future full-image runs should use
`prepare --target-size 64G`. This is a VM capacity requirement, not a change to
the workstation's disks. The one-use full-image bootstrap disk/export were
removed after successful installation and boot; the installed VM and evidence
remain available.

The Finite image initially booted with two failed services: its OSTree-only
first-boot dependency started `rpm-ostreed` against a native sysroot with no
OSTree repository, and signed ZFS/v4l2loopback modules lacked their enrolled MOK
in the direct-boot VM. `native-service-diagnosis.txt` retains the exact failures.
Nix policy installation and persistent Nix provisioning succeeded.

`configure-finite.py` provides explicit per-VM setup for these requirements:
native-backend conditions on both `finite-firstboot-rpm-ostree` and
`rpm-ostreed`, plus a Fedora shim entry and the image's existing akmods public
certificate in the VM MOK store. This leaves the signed image unchanged and
does not disable module verification. Subsequent qualification requires the
exact certificate to be exported from MOK, both modules actually loaded, both
OSTree-only units skipped by their conditions, and no failed services. These
configuration requirements must be integrated into a production native profile;
the published image alone is not qualified as an automatic migration.

The configured Finite run passed upgrade and rollback with the same signed
module trust and zero failed services. The extra shim-chain loader copy remained
systemd 259.10; loader/shim/SBAT update handling needs a production design before
this chain can replace the workstation's recovery path.

## Scope still requiring qualification

The update changes a revision marker and regenerates its signed UKI; kernel and
systemd versions are unchanged. These results cover deployment selection,
integrity verification, `/etc` merging and `/var` persistence, not a new kernel
release or loader version. The Fedora fixture boots directly through its
firmware db certificate; the configured Finite VM additionally tests Fedora
shim and MOK module trust. Workstation-specific firmware/shim behavior,
encrypted-root/FIDO2 unlock, desktop
login, TPM measurements, and physical firmware recovery require separate tests.
Rollback is explicitly requested; automatic recovery from an unbootable image
is not demonstrated or promised.

Native composefs currently requires a separate installation. The workstation's
600 MiB ESP also lacks the measured space needed for staged and rollback UKIs.
Neither issue is resolved by a VM pass. Keep the existing recovery path until a
storage and migration design has been tested on the actual replacement system.

Upstream references: [sealed image build pattern](https://bootc.dev/bootc/building/bootc-sealed-images.7.html),
[composefs integrity and limitations](https://bootc.dev/bootc/bootc-composefs.7.html),
and [persistent root-mount configuration](https://bootc.dev/bootc/man/bootc-setup-root-conf.5.html).

## Production-sealer fixture validation, 2026-11-18 UTC

The new host sealer was independently run twice with the disposable Fedora VM
key. Both archives were byte-identical, SHA256
`d46e61157e9bc0da25d15b2ff7b030e46a4524286beb2158579d5129d7046374`.
A fresh canonical import of each finished OCI archive matched its signed UKI.
The source-built pinned Nix importer also reproduced the earlier Fedora
importer's result on the original diagnostic artifact.

The new sealed archive then installed onto a fresh file-backed 32 GiB ext4 VM
disk and booted with Secure Boot enabled, kernel lockdown, enforcing SELinux,
required fs-verity and zero failed units. The runtime root digest matched the
sealing receipt. This run used one 3 GiB/two-CPU VM after sequential contract
checks finished; the VM was powered off afterwards. Evidence is under
`artifacts/native-sealer-boot/`, including `qualification.json`, the install and
first-boot console logs, `first-boot-evidence.txt` and `first-boot-bootc.json`.

The current EFI-update helper was additionally tested on a loop-mounted scratch
FAT filesystem in that guest. All seven interrupted file writes recovered. A
committed generation restored after unmount/remount, repeat application was
idempotent, old recovery paths survived, and a read-only FAT filesystem check
was clean. `efi-fat-result.json` records this file-transaction result. Its inert
payloads do not establish shim/SBAT or firmware acceptance. Reproduce it with
`run.py efi-fat --state artifacts/native-sealer-boot`.

These results exercise the production sealer's implementation with a VM key.
They do not qualify production-key signing, either full profile's changed
recipe, encrypted Btrfs, XBOOTLDR coexistence or an actual kernel/loader-version
upgrade. Those remain separate release and hardware-migration gates.

A separate loop-disk probe supplied a 600 MiB ESP, a 4 GiB VFAT XBOOTLDR
mounted at `/boot`, and a fresh ext4 root. `bootc install to-filesystem` with
the native backend, systemd-boot and generic-image mode returned success, but
placed every UKI and loader entry on the ESP; XBOOTLDR remained empty.
`xbootldr-probe-result.json` retains the file lists and installer output.
Reproduce with `run.py xbootldr-probe --state artifacts/native-sealer-boot`.
This confirms the approved layout is not implemented by bootc 1.17.1. It is a
failed storage-compatibility gate, not an encrypted coexistence rehearsal.
No workstation layout or firmware was changed.

## Pinned upstream XBOOTLDR installation and boot, 2026-11-18 UTC

The merged upstream fix, `8275daa9227f7c4ee893c0b05b4134dc2ff11283`, was
compiled as a native Fedora RPM without a downstream source patch. The same
RPM supplied the installer CLI and the installed OS, including initramfs setup.
Its declared version remains 1.17.4; this is a snapshot containing the fix,
not an unreleased version labelled 1.17.5.

Fresh installation onto a file-backed 32 GiB disk passed with a 600 MiB ESP,
4 GiB VFAT XBOOTLDR and unencrypted ext4 root. The installed system booted
through Secure Boot OVMF with kernel lockdown, enforcing SELinux, required
fs-verity and zero failed services. UKIs and loader entries were on XBOOTLDR;
the loader remained on the separate ESP, with no UKIs there. Booted executable
hashes matched the installer's checked RPM, and the booted root digest matched
the independently verified signed OCI archive. The VM was powered off.

Evidence is under `artifacts/xbootldr-install-final/`: `qualification.json`,
`preparation.json`, install/boot logs, `first-boot-bootc.json` and
`xbootldr-boot.json`. The runtime package receipt and independent integrity
report are under `artifacts/bootc-runtime-build/`. The final archive SHA256 is
`26e2e601cf0bcc9b2a72757709eac78784795bd83ab7cb436fcefba6381aa523`.
Installation used 1.5 GiB of guest RAM; successful boot verification used
1 GiB, with a 2 GiB host startup reserve. The initial placement assertion
selected an automount wrapper; the corrected check selects the underlying FAT
mount. Its failed diagnostic is retained as `xbootldr-check-autofs.log`.

Signing used only the disposable VM key. Final archive generation completed,
but the sealer's last verification import failed under a 1 GiB memory cap.
A separate independent verification at 2 GiB succeeded on those same completed
archive bytes. The failed sealer log is retained; no successful production
sealing receipt is claimed for that invocation.

Per the operator's selected scope, this run covers fresh installation and boot;
it performs no update or rollback cycle. It does not qualify either complete
Finite profile, encrypted Btrfs, production signing or preservation/migration
of the workstation's existing OSTree installation. No hardware disk or firmware
was changed. See [runtime integration and official-release transition](bootc-runtime.md).
