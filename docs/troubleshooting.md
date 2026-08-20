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
- `runner-capacity-before.txt` and `runner-capacity-after.txt` for storage
  exhaustion.

Verify a completed artifact with:

```bash
sha256sum --check SHA256SUMS
gh attestation verify purplefin-*.iso \
  --repo declarative-dale/purplefin
```

## Dell XPS 13 9350

Use [Dell XPS 13 9350](dell-xps-9350.md) for battery, display, authentication,
power, and camera checks. The out-of-tree camera-module signature policy is in
[Dell XPS 13 9350 Secure Boot status](dell-xps-9350-secure-boot.md).
