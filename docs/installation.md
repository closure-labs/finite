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
