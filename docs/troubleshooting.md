# Troubleshooting

## Inspect the active deployment

```bash
bootc status
rpm-ostree status
journalctl -b -p warning
```

If an upgrade fails, retry with the image reference shown by `bootc status`:

```bash
run0 bootc upgrade
```

Return to the previous deployment with:

```bash
run0 bootc rollback
run0 systemctl reboot
```

## Diagnose repository checks

Run the complete graph with build logs:

```bash
nix shell --accept-flake-config .#ci-check -c purplefin-ci-check
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
systemctl status purplefin-nix-selinux.service purplefin-nix-seed.service nix.mount
systemctl status nix-daemon.socket nix-daemon.service determinate-nixd.socket
findmnt /nix
```

`/nix` must be a writable bind mount backed by `/var/home/nix`. Purplefin
initializes an empty state from the immutable image seed, but deliberately
refuses to replace a non-empty malformed state. If
`purplefin-nix-seed.service` reports malformed state, preserve
`/var/home/nix` for diagnosis before repairing or restoring it; rebooting or
upgrading the bootc image will not erase it.

If `/nix/var/nix` is absent and `nix` warns that it is using a per-user chroot
store, confirm that the active image contains Purplefin's Determinate unit and
immutable activation links:

```bash
grep -F 'ExecStart=@/usr/bin/determinate-nixd' \
  /usr/lib/systemd/system/nix-daemon.service
readlink /usr/lib/systemd/system/multi-user.target.wants/nix-daemon.service
readlink /usr/lib/systemd/system/sockets.target.wants/nix-daemon.socket
```

All three checks should succeed. A corrected image upgrade followed by a reboot
restores these vendor files without replacing valid state in `/var/home/nix`.
Purplefin also removes stale daemon socket files after mounting that state and
before systemd binds the new sockets.

## Diagnose a local image build

```bash
podman info
podman images --digests
nix shell --accept-flake-config .#ci-image-build \
  -c purplefin-image-build base-generic localhost/purplefin:debug
```

Check that the requested profile exists:

```bash
nix build .#generated
jq '.profiles | keys' result/bootc/generated/profile-catalog.json
```

## Diagnose an installer build

Download both the installer and diagnostics artifacts from the workflow run.
Check:

- `installer-manifest.json` for the payload and Image Builder digests;
- `installer-environment.log` for container construction failures;
- `image-builder-pull.log` for pinned Image Builder image pull failures;
- `image-builder.log` for ISO generation failures;
- `qemu-smoke.log` or `qemu-boot.log` for boot-test failures;
- `qemu-install.log` for unattended Anaconda failures or the 20-minute limit;
- `qemu-installed-boot.log` for digest, update-reference, or three-minute boot
  readiness failures;
- `qemu-kickstart-server.log` to confirm that the guest fetched
  `purplefin-ci.ks` within three minutes;
- `runner-capacity-before.txt` and `runner-capacity-after.txt` for storage
  exhaustion.

Verify a completed artifact with:

```bash
sha256sum --check SHA256SUMS
gh attestation verify purplefin-*.iso \
  --repo closure-labs/finite
```

## Dell XPS 13 9350

Use [Dell XPS 13 9350](dell-xps-9350.md) for battery, display, authentication,
power, and camera checks. The out-of-tree camera-module signature policy is in
[Dell XPS 13 9350 Secure Boot status](dell-xps-9350-secure-boot.md).
