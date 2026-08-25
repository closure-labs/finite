# Finite installer

Finite follows Project Bluefin's native ISO architecture. The repository pins
`projectbluefin/dakota-iso`, the `projectbluefin/bootc-installer` Flatpak,
Dakota's Debian Bookworm fallback, and OSBuild Image Builder in
[`sources/bluefin-installer.json`](../sources/bluefin-installer.json), applies
the small Finite overlay in [`live/finite`](live/finite), and embeds a verified
Finite bootc image for a fully offline installation.

## Build pipeline

`nix shell .#ci-installer-build -c finite-installer-build` performs the same
build used in GitHub Actions:

1. Resolve the requested published Finite tag to an immutable digest.
2. Verify its Cosign signature, provenance, and SPDX attestation.
3. Resolve the matching foundation (`bluefin` or `bluefin-dx`) and construct or
   reuse its signed live-installer seed.
4. Validate that the selected payload is the foundation's generic profile;
   its installer recipe is already part of the reusable seed.
5. Pass that seed directly to Image Builder's `bootc-generic-iso` pipeline,
   with an explicit Fedora release derived from the foundation metadata, to
   copy the verified payload directly from host containers-storage into the
   live filesystem and assemble the GRUB2 ISO without an intermediate OCI
   archive.
6. Write `installer-manifest.json` plus `SHA256SUMS`.

The seed is deliberately the generic installer for one foundation. Its identity is
derived from the foundation image digest, pinned ISO source revision, pinned
installer bundle and builder digests, and Finite overlay. Trusted `main` builds publish
and sign it at `ghcr.io/closure-labs/finite-installer-seed`; pull requests may
reuse a verified seed but never publish one.

The seed build deliberately disables per-instruction Podman layers. Hosted CI
storage can otherwise copy up the complete Bluefin root filesystem after every
Dakota Dockerfile instruction; the signed seed is the reusable cache boundary,
so those intermediate layers add substantial time without reuse value. Runner
diagnostics record the active Podman graph driver and status.

There is no derived live-image configuration build after the seed boundary.
Hosted runners without native overlay diffs otherwise reserialize the complete
live image even when the added configuration is only a few files.

## Validation

The composite action exposes three separate phases:

- smoke boot the live ISO under OVMF and wait for
  `FINITE_INSTALLER_READY=1`, which is emitted only after the Flatpak's own
  `installer-debug.log` records application activation;
- run the installer's unattended JSON recipe against a disposable disk and
  stream the installer's result log to the serial diagnostics, close its
  persistent Done screen, and wait for `FINITE_INSTALLER_COMPLETE=1`;
- boot the installed disk with a fresh OVMF variable store, parse its reported
  bootc status, and require the update reference plus the linux/amd64 manifest
  digest to match the raw `containers-storage:` source consumed by bootc in the
  live environment. The signed registry digest remains the provenance identity;
  the source-manifest comparison accounts for Image Builder's offline storage
  conversion without weakening the installed-image check.

Image Builder owns SquashFS and hybrid GRUB2 ISO construction. Its OSBuild
manifest and build log are retained with the validation diagnostics so stage
timing and assembly inputs remain inspectable.

The installed disk contract is Project Bluefin's GRUB2 layout: a GPT with an
EFI system partition, separate `/boot`, and a Btrfs system partition. CI keeps
the serial logs and the normalized partition table as diagnostics.

The installer is launched by a globally enabled systemd user service attached
to `graphical-session.target` and conditioned on
`/etc/bootc-installer/live-iso-mode`. `FINITE_INSTALLER_ERROR=` reports a
Flatpak exit, a missing application log, an activation timeout, or an installer
result failure. The host-side unattended check separately limits activation to
120 seconds so a missing live-user session cannot consume the full installation
timeout.

See [Installation](../docs/installation.md) for user-facing installation and
artifact verification instructions.
