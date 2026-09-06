# Development

Edit the four recipes directly. Shared modules live under `recipes/shared`.
System files live in `files/system`, repository definitions in `files/dnf`, and
Nix lifecycle helpers in `files/scripts/lib`. BlueBuild copies these authored
assets into the image.

```bash
nix build --accept-flake-config --no-link .#ci-checks
bash scripts/bluebuild/stage.sh bluefin-generic
bluebuild validate recipes/bluefin-generic.yml
bluebuild generate --registry ghcr.io --registry-namespace closure-labs \
  recipes/bluefin-generic.yml
```

Use CLI v0.9.37. `stage.sh` creates the ignored `files/payload` directory from Nix.
Stage the selected profile before each build; next profiles include the locked
kernel RPMs. Home Manager first-login consumers use
foundation and hardware from the compact `/usr/share/finite/profile.json`.

Prefer hosted GitHub Actions for full image builds and ISO generation. Local
schema validation, shell/workflow linting and lifecycle fixture tests are small;
four Bluefin images and UEFI VMs require substantial storage. Inspect a Nix dry
run before fetching large dependencies and avoid concurrent local image builds.

The reference checkout revisions used for implementation are recorded in
[reference-revisions.json](bluebuild/reference-revisions.json). Workshop is an
optional reference, not a development dependency.

Before deploying image or installer changes, verify all four signed images and install generic and
next variants with the manual **Test ISO in UEFI VM** workflow. Check first boot, Nix SELinux setup, Home
Manager activation, persistence over upgrades, signature rejection and rollback.
Install an upstream ISO and confirm subsequent bootc updating. A separate
hardware cutover must retain the previous
workstation deployment and verify graphics, PipeWire camera, Espanso,
suspend/resume and authentication.

## Sandbox acceptance evidence

Verified runs for the BlueBuild replacement:

| Check | Result | Evidence |
| --- | --- | --- |
| Four signed profiles, final-image assertions and `CI gate` | Passed | [Build 34006442823](https://github.com/closure-labs/finbox/actions/runs/34006442823) |
| Four profiles with read-only publication permissions and no signing secret | Passed | [Validation 33999999603](https://github.com/closure-labs/finbox/actions/runs/33999999603) |
| Generic ISO generation with installer v1.5.0 and root finalization | Passed | [ISO 34005801360](https://github.com/closure-labs/finbox/actions/runs/34005801360) |
| Generic UEFI installation, Nix/SELinux, Home Manager, signature rejection, update and rollback | Passed | [VM 34006462352](https://github.com/closure-labs/finbox/actions/runs/34006462352) |
| Next-kernel ISO generation with installer v1.5.0 and root finalization | Passed | [ISO 34006463272](https://github.com/closure-labs/finbox/actions/runs/34006463272) |
| Next UEFI installation, expected kernel, Nix/SELinux, Home Manager, signature rejection, update and rollback | Passed | [VM 34007158009](https://github.com/closure-labs/finbox/actions/runs/34007158009) |
| Root remounting on first boot, update and rollback, both variants | Passed | Both VM runs above |

The generic VM installed signed index
`sha256:c2ad1b5523074eddf9ed2d07dd3d396e6f1c5475e43aeba514aaf46d37b7eaba`,
switched to the signature-enforced `bluefin-generic` channel, and rolled back to
its original deployment checksum. Run artifacts contain the architecture
manifest digests, bootc status records and service logs. Production and physical
workstation acceptance remain separate gates.

The earlier functional runs also reported `systemd-remount-fs.service` failing at boot.
The next VM's journal and fstab confirmed [bootc issue 971](https://github.com/bootc-dev/bootc/issues/971):
physical Btrfs root options were reapplied to the composefs overlay. Installer
root finalization now removes that entry after verifying the boot arguments.
Both corrected ISOs passed all three boots with successful remounting.
The hosted AMD runners also report the inherited `mcelog` service as unsupported
on their processors; the Nix and root mount service assertions pass.
