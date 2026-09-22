# Troubleshooting

Start with the section matching the problem. Include the running image and
relevant logs when reporting an issue.

## Kernel panic before LUKS unlock

If boot stops with `VFS: Unable to mount root fs on unknown-block(0,0)` before
the passphrase or security-key prompt, select the previous working Finite
deployment in the boot menu. Retain that deployment until the replacement has
booted successfully.

On the affected workstation, inspect `/boot/loader/entries/*.conf`. Each Finite
entry should reference both its kernel (`linux`) and initramfs (`initrd`). The
September 22, 2026 next-kernel image lacked
`/usr/lib/modules/7.2.6-300.fc45.x86_64/initramfs.img`, producing an entry with no
`initrd` line. Without that early userspace, encrypted root cannot be unlocked.
Changing YubiKey enrollment does not repair the missing boot payload.

The image build now regenerates the replacement kernel's initramfs and verifies
its OSTree, LUKS and FIDO2 support. See
[qualification policy](workstation-qualification.md) for the associated CI fix.

## Check the running system

```bash
sudo bootc status
rpm-ostree status
cat /usr/share/finite/profile.json
journalctl -b -p warning
```

`bootc status` shows the booted, staged and rollback deployments. See
[Install and update](installation.md#update-your-system) for upgrade and
rollback commands.

## First-login setup or app activation fails

Open the selector again with `finite-configure`. Check its user service and
build your current configuration to see the underlying error:

```bash
systemctl --user status finite-home-first-login.service
journalctl --user -b -u finite-home-first-login.service
nh home build
```

Your choices are in `~/.config/finite/profile.json`; personal settings are in
`~/.config/home-manager/customize.nix`. The initializer keeps timestamped
`home-manager.previous.*` directories when replacing a configuration.

## Nix does not start

Inspect persistent-state initialization, its mount, and the daemon sockets:

```bash
systemctl status finite-nix-seed.service finite-nix-selinux.service nix.mount
systemctl status nix-daemon.socket nix-daemon.service determinate-nixd.socket
journalctl -b -u finite-nix-seed -u finite-nix-selinux -u nix-daemon
findmnt /nix
```

`/nix` is a writable bind mount backed by `/var/home/nix`. First boot initializes
it from `/usr/lib/finite/determinate-nix-seed` and installs the SELinux policy
before starting the daemon sockets. Allow this initialization to complete.

If the seed service reports malformed persistent state, preserve `/var/home/nix`
for diagnosis and restore or repair that state before retrying. The service
protects existing data by stopping on an invalid nonempty directory.

## Nix apps need GPU setup

If Ghostty reports `Failed to create EGL display`, check whether
`/run/opengl-driver` is missing even though the tmpfiles configuration exists.
The store-backed configuration cannot be read during the early tmpfiles pass.
Finite restores it after mounting `/nix`:

```bash
systemctl status finite-nix-gpu.service
journalctl -b -u finite-nix-gpu.service
sudo systemctl restart finite-nix-gpu.service
```

Close and reopen the affected application after restoring the driver link.

Check the driver link and its persistent configuration:

```bash
readlink /run/opengl-driver
readlink /etc/tmpfiles.d/non-nixos-gpu.conf
readlink /nix/var/nix/gcroots/non-nixos-gpu.conf
```

Run the helper from the current Home Manager profile when activation requests it:

```bash
sudo "$(command -v non-nixos-gpu-setup)"
```

See [GPU configuration](configuration.md#enable-gpu-access-for-nix-apps) for the
supported graphics path.

## Home Manager reports a missing custom input

Check `journalctl --user -b -u finite-home-first-login.service`. If the error
names an input used by `customize.nix`, verify its declaration in
`~/.config/home-manager/flake.nix` and its pin in `flake.lock`. Older Finite
initializers preserved the customization module but replaced the flake and
lock during image upgrades. The corrected initializer preserves all three.

Restore a missing flake or lock from the timestamped
`~/.config/home-manager.previous.*` backups before retrying. A failed staged
build leaves the existing configuration in place. For a newly added input,
run `nix flake lock ~/.config/home-manager`, then `nh home build` and
`nh home switch`. See [custom flake inputs](configuration.md#add-custom-flake-inputs).

## An update reports a 1980 timestamp

An error saying the target is dated `Tue 01 Jan 1980` and is chronologically
older than the installed deployment indicates an image build timestamp problem.
Nix development shells export `SOURCE_DATE_EPOCH=315532800`; Docker Buildx
inherits it and dates the image to 1980. Finite's build wrapper clears that
variable before invoking BlueBuild. Rebuild and publish the affected channel
with the corrected wrapper, then retry the update.

For an already published image you intend to install, the one-time workaround
for this rpm-ostree timestamp check is:

```bash
sudo rpm-ostree upgrade --allow-downgrade
```

After the upgrade succeeds, reboot to activate it. The flag permits an older
deployment timestamp; it belongs to `rpm-ostree`, not `bootc`.

## An update fails signature verification

Compare the image reference and public key with the successful build's evidence.
Check the Finite entry in `/etc/containers/policy.json`, its public-key file,
and the registry's `use-sigstore-attachments` setting. The
[signing reference](ci-and-releases.md#image-signing) lists the expected files.

In the hosted acceptance test, a cryptographic rejection immediately after
**Testing rejection with the wrong signing key** is the expected result. The
next phase restores the correct policy and selects the signed update channel.

## A repository check fails

Run the suite with build logs and bounded local resources:

```bash
nix build --accept-flake-config --max-jobs 3 --cores 2 \
  --no-link .#ci-checks --print-build-logs
```

For a focused check, use an exported name such as
`.#checks.x86_64-linux.workflows`, `.#checks.x86_64-linux.nix-lifecycle` or
`.#checks.x86_64-linux.bluebuild`. Run `nix fmt` to apply formatting.

## An image or ISO build fails

Open the profile job in [Finite Actions](https://github.com/closure-labs/finite/actions).
For image builds, inspect the generated Containerfile, base digest, labels and
final-image verification log. For ISOs, inspect `installation.json`,
`signature.json`, `SHA256SUMS` and the installer log.

A profile/channel mismatch means the requested digest belongs to a different
recipe. Select a matching digest from a successful image build. ISO generation
uses that verified digest throughout the run.

The VM test streams the guest console and timestamps each phase. Its evidence
includes kernel versions, Nix readiness, mount layouts and bootc status across
first boot, updating and rollback.

## Dell camera or display issues

Use the [Dell XPS 13 9350 guide](dell-xps-9350.md) for display settings, PipeWire
camera checks and kernel diagnostics. The [Secure Boot checks](dell-xps-9350-secure-boot.md)
cover module paths and signatures.

Inspect the libcamera module and sensor tuning selected during camera enumeration:

```bash
LIBCAMERA_LOG_LEVELS='IPAManager:DEBUG,IPAProxy:DEBUG' cam -l
```

This lists cameras without capturing frames. A migrated workstation may retain
an OV02C10 helper in `/var/lib/finite/libcamera/ipa` and sensor calibration in
`/etc/libcamera/ipa/simple/ov02c10.yaml`. Keep both until the distribution's IPA
provides compatible sensor support. Camera enumeration alone does not establish
equivalent exposure or color handling: `Failed to create camera sensor helper`
indicates that the replacement lacks sensor-specific support.

When retiring an older module-path override in
`/etc/libcamera/configuration.yaml`, back up the module and tuning first. Remove
missing paths and migrate a still-needed helper to the Finite-owned location;
verify enumeration and the selected module before removing its old copy.
Existing camera sessions keep their loaded module until they close. Avoid
restarting PipeWire or WirePlumber during calls.
