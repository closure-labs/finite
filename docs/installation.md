# Install and update

Finite installs the Bluefin GNOME desktop on an x86_64 UEFI system. Choose
`bluefin-generic` for Bluefin or `bluefin-dx-generic` for Bluefin DX. Choose
`next` or `dev-next` when you need the pinned next kernel; the
[Dell guide](dell-xps-9350.md) covers the XPS 13 9350.

## Get an ISO

ISOs are generated on demand from a signed image. Repository maintainers can
start the workflows below; the resulting download appears in the run's
**Artifacts** section.

1. Open a successful [Build Finite run](https://github.com/closure-labs/finite/actions/workflows/build.yml)
   and download the selected profile's small image evidence artifact.
   Its `*-image-ref.txt` contains the image digest. From a Finite checkout with
   Cosign installed, verify that reference with `cosign verify --key cosign.pub IMAGE_REFERENCE`.
2. Open [Build installation ISO](https://github.com/closure-labs/finite/actions/workflows/iso.yml),
   choose **Run workflow** on `main`, and enter the digest and matching update
   channel. The digest starts with `sha256:`.
3. Download and extract the finished ISO artifact. In its directory, verify:

   ```bash
   sha256sum -c SHA256SUMS
   ```

4. Read `installation.json` to confirm the image, profile and continuing update
   channel. Write the ISO to installation media with your preferred image writer.

The ISO uses the Kinoite installer interface and installs the selected Bluefin
GNOME image. Back up the target system before choosing its installation disk.

## Install and sign in

Boot the installation media in UEFI mode, follow the installer, and boot the
installed system. At first login, Finite prepares Nix and opens the environment
selector. Choose any combination of roles and optional packages, or keep the
base environment. You can open the selector again with `finite-configure`.

If Home Manager prints a GPU setup command, follow the
[GPU setup steps](configuration.md#enable-gpu-access-for-nix-apps).

The ISO records a one-time installation source. After installation, confirm the
running profile and choose the continuing channel listed in `installation.json`:

```bash
sudo bootc status
cat /usr/share/finite/profile.json
cat /usr/share/finite/update-image
```

For a generic Bluefin installation:

```bash
sudo bootc switch --enforce-container-sigpolicy \
  ghcr.io/closure-labs/finite:bluefin-generic
sudo bootc status
sudo systemctl reboot
```

Review the staged image in `bootc status` before rebooting. Use your selected
channel in the command; for example, the DX next channel is `dev-next`.

## Update your system

Fetch and stage the next image on your current channel:

```bash
sudo bootc upgrade
sudo bootc status
sudo systemctl reboot
```

Your home directory and persistent Nix state carry across image updates.
Finite refreshes the managed Home Manager template at login while preserving
your `flake.nix`, `flake.lock`, `customize.nix` and `modules/local.nix`.
Custom inputs and dependency pins survive image upgrades; see
[custom flake inputs](configuration.md#add-custom-flake-inputs).

To refresh the independent package inputs in your Home Manager configuration:

```bash
nix flake update --flake ~/.config/home-manager
nh home build
nh home switch
```

## Return to a previous system

Stage the previous deployment, review it, then reboot:

```bash
sudo bootc rollback
sudo bootc status
sudo systemctl reboot
```

Before a hardware or channel transition, retain the current deployment with
`sudo ostree admin pin booted`. Check graphics, camera, Espanso, suspend/resume
and authentication after booting the new image. Existing installations need
the [current signing key and registry policy](ci-and-releases.md#image-signing)
before selecting signature-enforced updates.

## How the installer is built

The workflow verifies an image digest and copies it to a unique short tag for
BlueBuild's `generate-iso`. `installation.json` records the source digest,
update channel and installer inputs; `SHA256SUMS` covers the ISO and that record.

`sources/bluebuild-installer.json` pins upstream installer v1.5.0. The ephemeral
runner adds Finite's post-install hook and supplies the local alias expected by
CLI v0.9.37. The hook verifies the physical-root boot arguments and finalizes
`fstab` for composefs, preserving the other mounts. See the
[bootc installation reference](https://github.com/bootc-dev/bootc/blob/main/docs/src/bootc-install.md).

The [hosted VM test](development.md#validate-an-iso) checks installation, first
boot, signed updating, persistent configuration and rollback.
