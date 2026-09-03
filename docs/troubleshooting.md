# Troubleshooting

## Inspect the active deployment

```bash
bootc status
rpm-ostree status
journalctl -b -p warning
```

If an upgrade fails, retry with the image reference shown by `bootc status`:

```bash
sudo bootc upgrade
```

Return to the previous deployment with:

```bash
sudo bootc rollback
sudo systemctl reboot
```

## Diagnose repository checks

Run the complete graph with build logs:

```bash
nix shell --accept-flake-config .#ci-check -c finite-ci-check
```

Run a single named check when isolating a failure:

```bash
nix build .#checks.x86_64-linux.shell --print-build-logs
nix build .#checks.x86_64-linux.workflows --print-build-logs
nix build .#checks.x86_64-linux.bootc --print-build-logs
```

Confirm formatting independently with `nix fmt`.

## Determinate Nix does not start

Check the persistent-state provisioning and mount before inspecting the daemon:

```bash
systemctl status finite-nix-selinux.service finite-nix-seed.service nix.mount
systemctl status nix-daemon.socket nix-daemon.service determinate-nixd.socket
findmnt /nix
```

`/nix` must be a writable bind mount backed by `/var/home/nix`. Finite
initializes an empty state from the immutable image seed, but deliberately
refuses to replace a non-empty malformed state. If
`finite-nix-seed.service` reports malformed state, preserve
`/var/home/nix` for diagnosis before repairing or restoring it; rebooting or
upgrading the bootc image will not erase it.

If `/nix/var/nix` is absent and `nix` warns that it is using a per-user chroot
store, confirm that the active image contains Finite's Determinate unit and
immutable activation links:

```bash
grep -F 'ExecStart=@/usr/bin/determinate-nixd' \
  /usr/lib/systemd/system/nix-daemon.service
readlink /usr/lib/systemd/system/multi-user.target.wants/nix-daemon.socket
readlink /usr/lib/systemd/system/multi-user.target.wants/determinate-nixd.socket
test ! -e /usr/lib/systemd/system/sockets.target.wants/nix-daemon.socket
```

All four checks should succeed. The daemon itself is socket-activated; it must
not also be enabled directly under `multi-user.target`. A corrected image upgrade followed by a reboot
restores these vendor files without replacing valid state in `/var/home/nix`.
Finite also removes stale daemon socket files after mounting that state and
before systemd binds the new sockets.

## Nix applications do not use the GPU

Confirm that the Home Manager driver link exists and that its target remains in
the Nix store:

```bash
readlink /run/opengl-driver
readlink /etc/tmpfiles.d/non-nixos-gpu.conf
readlink /nix/var/nix/gcroots/non-nixos-gpu.conf
```

If `/run/opengl-driver` is absent or `nh home switch` reports driver drift, run
the setup package from the current Home Manager profile:

```bash
sudo "$(command -v non-nixos-gpu-setup)"
```

This updates only the tmpfiles rule, its GC root, and the runtime driver link;
it does not modify the immutable bootc filesystem.

## Diagnose a local image build

```bash
podman info
podman images --digests
nix shell --accept-flake-config .#ci-image-build \
  -c finite-image-build bluefin-generic localhost/finite:debug
```

Check that the requested profile exists:

```bash
nix build .#generated
jq '.profiles | keys' result/bootc/generated/profile-catalog.json
```

## Diagnose an installer build

Download both the installer and diagnostics artifacts from the workflow run.
Check:

- `installer-manifest.json` for the payload, seed, and pinned installer inputs;
- `payload-inspect.log` and `seed-inspect.log` for GHCR resolution failures;
- `source-prepare.log` for the exact pinned Dakota source-patching stage;
- `live-environment.log` for the single-commit live-seed construction;
- `seed-preflight.log` for missing Btrfs or other Fisherman executables, recipe
  validation, registry resolution, payload inspection, and scratch capacity;
- `seed-pull.log` or `seed-push.log` for signed SquashFS artifact transfer;
- `squashfs-build.log` and `iso-build.log` for LZ4 or ISO assembly failures;
- `qemu-smoke.log` or `qemu-boot.log` for boot-test failures;
- `qemu-install.log` for unattended bootc-installer failures or the 30-minute
  limit; `FINITE_INSTALLER_ERROR=` is fatal and identifies early Flatpak exits,
  a missing application log, an activation timeout, or a reported install
  failure;
- `installer-debug.log`, `fisherman-output.log`, `preflight.log`, and
  `system-state.log` for the complete guest-side failure evidence extracted
  from the serial stream before poweroff;
- `FINITE_INSTALLER_READY=1` in the serial log to confirm the Flatpak's own
  `installer-debug.log` reached `do_activate`; this marker does not merely mean
  GDM started;
- `FINITE_INSTALLER_COMPLETE=1` in that log to confirm the installer returned
  successfully and the CI first-boot probe was written;
- `qemu-installed-boot.log` for UEFI startup, digest, update-reference, or
  five-minute boot readiness failures; an empty guest log indicates a firmware
  or GRUB failure before the kernel starts;
- `installed-partitions.json` for the required GPT, EFI system partition,
  separate `/boot`, and Btrfs system partition;
- `runner-capacity-before.txt` and `runner-capacity-after.txt` for storage
  exhaustion. On a cache hit, Dakota and SquashFS construction are skipped;
  the action summary identifies `github-actions` or `ghcr` as the cache source.

If the live guest reaches GDM or a login prompt without either installer
marker, inspect the globally enabled `finite-installer.service` user unit and
the live user's graphical session. The former XDG autostart plus
`live-ready.service` path could report readiness as soon as GDM started while
never creating a live-user installer process; the host now fails this case at
the short launcher deadline instead of waiting for the 30-minute install limit.

Verify a completed artifact with:

```bash
sha256sum --check SHA256SUMS
gh attestation verify finite-*.iso \
  --repo closure-labs/finite
```

## Dell XPS 13 9350

Use [Dell XPS 13 9350](dell-xps-9350.md) for the optional Home Manager display
policy and Fedora 7.2 IPU7 camera checks. The in-tree module signature contract
is in [Dell XPS 13 9350 Secure Boot status](dell-xps-9350-secure-boot.md).
