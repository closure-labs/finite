# Installation

Build an on-demand ISO from a verified Finite image using GitHub Actions.

1. Open a successful **Build Finite** run in `closure-labs/finite`. Select a
   profile's image evidence, obtain its digest and verify it with the tracked key:
   `cosign verify --key cosign.pub ghcr.io/closure-labs/finite@sha256:…`.
2. Dispatch **Build installation ISO** on `main` with that digest and its channel
   (`bluefin-generic`, `next`, `bluefin-dx-generic` or `dev-next`). The signed digest
   must belong to the selected profile; daily builds may advance the channel
   while the ISO request is queued.
3. Download the ISO artifact, then run `sha256sum -c SHA256SUMS` beside the ISO
   and `installation.json`. Check the source and update channel in that record.
4. Boot the ISO in a disposable UEFI VM and install. The Kinoite variant selects
   the installer interface; the installed desktop remains Bluefin/GNOME.
5. After installation, compare `bootc status --json` with the recorded source
   digest and inspect `/usr/share/finite/profile.json`. Test first login and Nix
   persistence before selecting the continuing update channel.

Each ISO uses a short random tag, checked against existing registry tags before
copying. Its length fits the installer's 32-byte volume-label limit. CLI
v0.9.37 loses digest-only references when constructing installer arguments; the
workflow verifies a digest, copies it to this unique tag with digest preservation,
and passes the tag to `generate-iso`. Do not use that one-time tag as a permanent
update channel.

The workflow uses upstream installer v1.5.0, pinned by digest in
`sources/bluebuild-installer.json`. CLI v0.9.37 hardcodes the older v1.4.0 image,
so the ephemeral ISO runner builds a small derivative containing Finite's
post-install hook and gives it that local alias. It explicitly uses Docker and
changes no upstream registry tags. `installation.json` records the upstream
version and digest, local image ID, hook checksum, Finite revision and alias.
This avoids the older Lorax cleanup that removes `load_policy`, causing
Anaconda to fail at shutdown after installation reports completion. A preflight
check rejects an installer that still removes this SELinux utility.

The hook uses the installer's supported `install_*` post-script mechanism. It
removes only `/` from the installed `fstab`, after checking that every boot entry
already identifies the physical root and any required Btrfs subvolume. Other
mounts remain intact. This follows [bootc's physical-root guidance](https://github.com/bootc-dev/bootc/blob/main/docs/src/bootc-install.md)
and avoids [the composefs remount conflict](https://github.com/bootc-dev/bootc/issues/971).

After validating the installed image and its signing policy, select the channel
recorded in `installation.json`. For example, in the disposable generic VM:

```bash
sudo bootc switch --enforce-container-sigpolicy \
  ghcr.io/closure-labs/finite:bluefin-generic
sudo systemctl reboot
```

Verify the staged digest and signature policy before rebooting. Then test an
upgrade, confirm Home Manager and `/var/home/nix` persist, and test rollback.
The image also records its canonical update reference in
`/usr/share/finite/update-image`.

The Nix seed lives under `/usr/lib/finite/determinate-nix-seed`. First boot copies
it into persistent `/var/home/nix`, installs the SELinux policy and mounts `/nix`
before enabling daemon sockets. Home Manager's first-login flow and standalone
configuration templates remain available; see [configuration](configuration.md).

Switch the running workstation separately after sandbox acceptance, retaining
its previous deployment.

## Hosted VM acceptance

Dispatch **Test ISO in UEFI VM** with a successful ISO workflow run ID. It verifies
the artifact checksums and source signature, installs a temporary unattended ISO
copy in a disposable UEFI VM, checks SELinux and the Nix daemon, activates the
base Home Manager environment, tests rejection with a wrong signing key, selects
the continuing channel, checks persistent Nix state/customization after updating,
and rolls back. It uploads logs and status records; disks and SSH keys stay on
the ephemeral runner and are removed. Run this for generic and next ISOs when validating changes to the image or installer. The script refuses local execution outside finite Actions.

The Actions log streams the guest console and timestamps each boot phase. The
unattended installer kernel must start within three minutes; installation has
a 45-minute limit. After SSH becomes available, the test waits up to three
minutes for every Nix initialization unit and daemon socket to become active.
It also requires the root remount service to succeed on each boot. Artifacts
retain console and service logs, fstab, and mount layouts for diagnosis.
