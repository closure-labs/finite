# Installation and updates

Purplefin can replace the image on an existing bootc system or be installed
with its graphical Anaconda ISO.

## Choose a profile

Common published tags are:

| Tag | Target |
| --- | --- |
| `latest` | Base workstation on generic x86-64 hardware |
| `developer-generic` | Developer workstation on generic x86-64 hardware |
| `support-generic` | Support workstation on generic x86-64 hardware |
| `dale` | Sales, training, and support on a Dell XPS 13 9350 |

The generated catalog contains every profile and tag:

```bash
nix build .#generated
jq '.profiles | with_entries(.value = .value.tags)' \
  result/bootc/generated/profile-catalog.json
```

## Switch an existing bootc system

Replace `latest` with the selected profile tag:

```bash
run0 bootc switch ghcr.io/declarative-dale/purplefin:latest
run0 systemctl reboot
```

Inspect the active and staged deployments:

```bash
bootc status
```

## Determinate Nix lifecycle

Purplefin first installs Fedora's supported `nix` and `nix-daemon` packages,
then uses the pinned Determinate Nix Installer to migrate that upstream Nix
installation to Determinate Nix. This follows Determinate Systems' migration
path while retaining Fedora's native filesystem, systemd, and sysusers
integration.

The Fedora `nix-filesystem` dependency supplies `/nix`; Purplefin does not
create that directory separately. Because bootc keeps the image root immutable
and `/nix` must be writable, first boot copies the image seed to persistent
`/var/home/nix` and bind-mounts it at `/nix` before the Nix daemon starts. Later
boots preserve that state, including installed packages and store paths.

Determinate Nixd owns Nix upgrades after migration. Use the normal Determinate
Nix upgrade mechanism rather than upgrading the runtime through Fedora's Nix
packages. A bootc upgrade may update the seed used by new installations, but
never overwrites an existing `/var/home/nix`.

## Install from ISO

1. Run the `Build and boot-test Purplefin installer ISO` workflow from `main`.
2. Select the profile to embed.
3. Download the `purplefin-<profile>-installer` workflow artifact.
4. Verify the checksums and GitHub attestation:

   ```bash
   sha256sum --check SHA256SUMS
   gh attestation verify purplefin-*.iso \
     --repo declarative-dale/purplefin
   ```

5. Write the ISO to installation media, boot it, and complete the graphical
   installer.

The artifact also contains `installer-manifest.json` and `qemu-boot.log`. The
manifest records the ISO, source commit, Image Builder, and embedded image
digests.

## Update or roll back

Stage the newest image for the current tag and reboot:

```bash
run0 bootc upgrade
run0 systemctl reboot
```

To return to the previous deployment:

```bash
run0 bootc rollback
run0 systemctl reboot
```

See [Troubleshooting](troubleshooting.md) for image, installer, and boot checks.
