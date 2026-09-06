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

## Diagnose an image build

Use the profile job's BlueBuild log and image evidence in finite Actions. Check
its generated Containerfile, resolved base digest and profile labels. The
assembled-image verification runs after upstream cleanup and checks the Nix
seed, signing policy, packages, kernel and bootc lint.

For lightweight local inspection:

```console
bluebuild validate recipes/bluefin-next.yml
bluebuild generate --registry ghcr.io --registry-namespace closure-labs recipes/bluefin-next.yml
nix build .#home-profile-catalog
jq . result
```

Stage the selected profile with `scripts/bluebuild/stage.sh` before a local
image build. Prefer hosted runners for the four full builds.

## Diagnose an ISO build

The manual ISO workflow validates its source digest and signature before creating
a unique installation tag. A profile/channel mismatch means the selected image
belongs to a different recipe. Advancing a channel does not change a queued ISO
request: generation uses the explicit verified digest.
Inspect the workflow log, `installation.json`, `signature.json` and `SHA256SUMS`.
The package must be readable by the installer. After a disposable VM installation,
compare `bootc status --json` with the source record and explicitly switch to the
selected continuing update channel. See [installation](installation.md).

## Dell XPS 13 9350

Use [Dell XPS 13 9350](dell-xps-9350.md) for the optional Home Manager display
policy and Fedora 7.2 IPU7 camera checks. The in-tree module signature contract
is in [Dell XPS 13 9350 Secure Boot status](dell-xps-9350-secure-boot.md).
