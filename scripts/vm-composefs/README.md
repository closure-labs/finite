# Native composefs VM qualification

These fixtures test upstream bootc native composefs, signed UKIs and
systemd-boot independently of the workstation's existing OSTree installation.
They are not production recipes or an in-place migration tool.

All writable disks and firmware variables live under this checkout's ignored
`artifacts/systemd-boot/` directory. The installer receives a conventional live
root disk, an empty 32 or 64 GiB target disk and a read-only payload disk containing
locally generated OCI archives. It sees no host physical disks. `install.sh`
requires the dedicated installer kernel argument, VM SMBIOS product name and
exact virtual target size before invoking the destructive installer.

The bootstrap installer uses direct kernel boot and permissive SELinux because
its exported conventional root has not been installed/relabelled by bootc.
It is not counted as a Secure Boot or enforcing-SELinux pass. The installed
candidate boots through Secure Boot OVMF, the signed systemd-boot loader and a
signed UKI with strict composefs digest verification. Runtime assertions require
kernel lockdown, enforcing SELinux and the native composefs backend.

Use fresh state directories for separate runs. VM signing keys and SSH private
keys must remain in those private directories; Containerfile signing uses secret
mounts, and only the SSH public key is copied into the fixture. The test account
and passwordless SSH provisioning belong only to the disposable VM image.

The Containerfile has separate `rootfs` and `candidate` targets. First build and
tag the rootfs; then build the sealed candidate with `ROOTFS_IMAGE` pointing to
that exact local rootfs. The layout follows bootc's documented split-kernel and
separate UKI tools stages. `Containerfile.update` creates a second rootfs with a
distinct revision marker; it must be sealed again to authenticate its new digest.

Both Docker and rootless Podman builds produced mounted trees whose directory
permissions/timestamps differed from the OCI import view. The installer
correctly rejected the UKI digest from the documented directory-based sealing
pattern. Diagnostics are retained under `vm` and `vm-docker`.

`seal-oci.py` is a separate VM diagnostic for that mismatch. It imports a local
candidate archive with bootc's own OCI importer, computes its bootable-root
digest, signs a replacement UKI with that digest, then re-imports the final
archive and requires an identical root digest. It accepts only localhost image
tags and keeps outputs under `artifacts`. Its temporary metadata repository uses
`init --insecure` so unprivileged build storage need not support fs-verity; this
does not relax the installed candidate's required fs-verity or Secure Boot.
This uses an internal bootc command and is not yet a production build interface.
Never disable digest verification to get past a build/import mismatch.

`run.py prepare --state PATH --engine docker` exports the rootfs/candidate and
creates the virtual disks and VM-only Secure Boot variables. It refuses to
overwrite existing disks. Use `--target-size 64G` for full Finite images so local
OCI archive unpacking and staging have enough working space. `install` boots the installer; `first-boot` boots the
installed system and collects evidence over localhost-only forwarded SSH.
`upgrade` mounts the payload under `/var/mnt/finite-vm-inputs`, switches to its
`update.oci.tar` and reboots; `rollback` restores
the prior deployment and reboots. Both check revision identity, the trust chain
and persistence of sentinel files in `/etc` and `/var`.

Run heavy builds and VMs sequentially on this workstation. QEMU defaults to
3072 MiB/two CPUs and refuses startup without a further 3 GiB of available host
memory. `--memory-mib 1024|1536|2048|3072|4096` selects a bounded alternative;
`--host-reserve-mib 2048|2560|3072|4096` sets the startup reserve. Small Fedora
fixtures can use less memory than full desktop images. Check host
memory pressure between phases; the startup check cannot reserve memory against
other applications that allocate it later.

For fresh XBOOTLDR validation, derive the Fedora fixture with
`Containerfile.xbootldr`, the staged runtime RPM and `install-native-bootc.sh`,
then seal it with a VM key and independently verify its final OCI archive.
`prepare-xbootldr.py` accepts that archive, its integrity report, the staged
runtime package directory and an existing disposable bootstrap:

```sh
python3 scripts/vm-composefs/prepare-xbootldr.py \
  --state artifacts/xbootldr-test \
  --bootstrap artifacts/systemd-boot/vm-docker \
  --archive artifacts/bootc-runtime-build/sealed-xbootldr.oci.tar \
  --integrity artifacts/bootc-runtime-build/integrity-xbootldr.json \
  --runtime-packages artifacts/bootc-runtime-build/packages
python3 scripts/vm-composefs/run.py install --state artifacts/xbootldr-test \
  --memory-mib 1536 --host-reserve-mib 2048
python3 scripts/vm-composefs/run.py first-boot --state artifacts/xbootldr-test \
  --memory-mib 1536 --host-reserve-mib 2048 --expect-xbootldr
```

Preparation uses userspace filesystem tools, without host mounts or a helper
VM. The guarded installer applies the checked RPM before creating a 600 MiB
ESP, 4 GiB VFAT XBOOTLDR and unencrypted ext4 root on its empty virtual disk.
First boot checks the runtime hashes, partition GUIDs/sizes and UKI placement
alongside the existing Secure Boot and integrity checks. This covers fresh
installation and boot only; it does not migrate an OSTree installation.

After installation, `run.py efi-fat --state PATH` checks the current production
EFI transaction helper on a loop-mounted 64 MiB scratch FAT filesystem inside
the guest. It interrupts all seven writes, restores the previous generation,
checks idempotence and committed recovery after remount, and runs a read-only
FAT check. It changes no VM boot files and uses inert payloads, so its result
is file-transaction evidence rather than shim/SBAT or firmware qualification.

When using the canonical diagnostic, copy the successful `canonical-base` and
`canonical-update` sealed archives to the payload directory as `base.oci.tar`
and `update.oci.tar`, and rebuild the payload filesystem before starting QEMU.
Do not replace a disk while a VM is running. The `result.json` files record the
pre/post sealing digest comparison. Consult the qualification report for actual
results; the existence of the harness does not establish a passing test.

`tamper` requires a completed rollback run, clones its disk/firmware, and changes
one signed UKI command-line byte. It requires both signature verification
failure and an explicit EFI loader authentication rejection before kernel
startup. It never modifies the passing VM's disk. See
[`docs/systemd-boot-vm-qualification.md`](../../docs/systemd-boot-vm-qualification.md)
for the current results and limitations.

The small Fedora bootc fixture validates the harness. Full Finite-derived images
must be qualified separately; a Fedora fixture result is not Finite qualification.

The full Finite VM additionally needs `configure-finite.py --state PATH` after
installation. It guards the OSTree-only first-boot job and daemon with
`native-firstboot.conf` in the guest's writable `/etc`, stages the existing
Fedora shim and signed systemd-boot in an isolated VM ESP directory, and
pre-enrolls the image's existing akmods certificate and the VM UKI certificate
in the VM's MOK store. This follows the repository's existing disposable-VM MOK
enrollment mechanism. It preserves signature enforcement and requires the real
ZFS/v4l2loopback modules to load with the expected MOK after reboot.

This is explicitly per-VM configuration, not a silently fixed production image.
The shim-chain loader copy needs a production update strategy before rollout;
the present update test uses an unchanged systemd version. The initial full-image
service failures and subsequent configuration are retained in the report.

`run.py xbootldr-probe --state PATH` probes native installation onto a fresh
16 GiB loop disk inside the already-installed fixture guest. It supplies a
600 MiB ESP and 4 GiB VFAT XBOOTLDR, records the actual file placement and
installer exit status, then unmounts and removes the scratch disk. It requests
generic-image mode to suppress firmware changes. This is a compatibility
probe, not an encrypted migration or successful boot test. With bootc 1.17.1
the installer returns success but leaves XBOOTLDR empty; see the qualification
report. Do not use that result to authorize the workstation migration.
