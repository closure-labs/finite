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
3. Build or reuse a signed, payload-independent Dakota live seed containing the
   pinned installer Flatpak and Finite branding.
4. Add a tiny target layer containing the immutable Finite install source and
   mutable update reference.
5. Create an LZ4 SquashFS and Dakota systemd-boot ISO without downloading or
   embedding the multi-gigabyte Finite payload.
6. Write `installer-manifest.json` and `SHA256SUMS`.

The ISO requires a network connection. The installed image is pulled by digest,
while the installed system tracks the selected Finite tag for future updates.
Trusted `main` builds publish and keylessly sign reusable seeds at
`ghcr.io/closure-labs/finite-installer-seed`; pull requests can reuse a seed
only after verifying its workflow identity.

## Validation

The composite action smoke-boots the live ISO under OVMF, performs an unattended
Dakota installation onto a disposable disk, then boots the installed system.
The final proof requires the installed bootc digest to equal the signed digest
selected before ISO assembly and the update reference to equal the selected tag.

The live ISO uses systemd-boot. The installed Fedora/Bluefin target deliberately
keeps Project Bluefin's GRUB2 layout: GPT, EFI system partition, separate
`/boot`, and Btrfs system partition. Serial readiness and result markers prevent
GDM or Dakota's persistent Done screen from being mistaken for success.

See [Installation](../docs/installation.md) for user-facing instructions.
