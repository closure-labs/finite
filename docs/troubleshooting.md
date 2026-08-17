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
nix flake check --print-build-logs
```

Run a single named check when isolating a failure:

```bash
nix build .#checks.x86_64-linux.shell --print-build-logs
nix build .#checks.x86_64-linux.workflows --print-build-logs
nix build .#checks.x86_64-linux.bootc --print-build-logs
```

Confirm formatting independently with `nix fmt`.

## Diagnose a local image build

```bash
podman info
podman images --digests
nix run .#image-build -- base-generic localhost/purplefin:debug
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
