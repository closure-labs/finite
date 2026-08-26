# Finite network installer

Finite uses Project Bluefin's Dakota ISO architecture and Dakota's graphical
`bootc-installer`; it does not use Anaconda or Kickstart. The immutable inputs
are recorded in [`sources/dakota-installer.json`](../sources/dakota-installer.json):
the Dakota ISO source, installer Flatpak, Dakota live image, and Debian
initramfs builder. The Finite branding and CI integration live in
[`live/finite`](live/finite).

## Build pipeline

`nix shell .#ci-installer-build -c finite-installer-build` performs the GitHub
Actions build:

1. Resolve the requested Finite tag and verify its Cosign signature, provenance,
   and SPDX attestation.
2. Verify the digest-pinned Dakota live image.
3. Build or reuse a signed, payload-independent Dakota seed artifact containing
   the completed LZ4 SquashFS, boot files, and Fisherman preflight proof.
4. Write the immutable Finite install source and mutable update reference to a
   small JSON file on the ISO. A pre-installer service validates and applies it
   to the writable live overlay at boot.
5. Assemble the Dakota systemd-boot ISO without rebuilding Dakota, recompressing
   the SquashFS, or downloading and embedding the multi-gigabyte Finite payload.
6. Write `installer-manifest.json` and `SHA256SUMS`.

The ISO requires a network connection. The installed image is pulled by digest,
while the installed system tracks the selected Finite tag for future updates.
Trusted `main` and scheduled builds publish and keylessly sign the SquashFS seed
artifacts at `ghcr.io/closure-labs/finite-installer-seed`; pull requests reuse
them only after verifying the trusted workflow identity. An exact-key GitHub
Actions cache accelerates retries of the same pull request without publishing
PR-built content as a trusted seed.

The exact seed key covers the Dakota live digest and source revision, installer
checksum, Debian builder digest, Finite live overlay and logo, and the seed
builder itself. It deliberately excludes the selected Finite payload digest and
update tag.

The live seed stages `btrfs`, `mkfs.btrfs`, and their private runtime libraries
from the pinned Debian builder. Its final Dakota customization is one mounted
build instruction and one image commit. Normal LZ4 mode is used; the slower
high-compression LZ4 option is deliberately disabled.

## Validation

The composite action smoke-boots the live ISO under OVMF, performs an unattended
Dakota installation onto a disposable disk, then boots the installed system.
The final proof first requires the source marker emitted by the live system to
equal the signed registry digest selected before ISO assembly. Fisherman's exact
installed OSTree deployment checksum is then recorded before shutdown and must
equal the checksum reported by the independently booted system. The update
reference must equal the selected tag. The bootc manifest digest is retained as
diagnostics but may differ because Fisherman copies the registry image through
a local OCI layout before installation.

The live ISO uses systemd-boot. The installed Fedora/Bluefin target deliberately
keeps Project Bluefin's GRUB2 layout: GPT, EFI system partition, separate
`/boot`, and Btrfs system partition. Serial readiness and result markers prevent
GDM or Dakota's persistent Done screen from being mistaken for success.

Before installation can touch the target disk, the live launcher checks every
required executable, runs `fisherman validate` against the selected recipe,
resolves and inspects the immutable network target, and requires at least 8 GiB
of disk-backed `/var/tmp` scratch space. Both the GUI and Fisherman logs plus
block devices, mounts, capacity, Podman storage, and installer journals are
copied to the serial diagnostics stream before an unattended shutdown.

See [Installation](../docs/installation.md) for user-facing instructions.
