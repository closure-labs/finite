# Troubleshooting

Start with the section matching the problem. Include the running image and
relevant logs when reporting an issue.

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
nix build --accept-flake-config --max-jobs 1 --cores 1 \
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
