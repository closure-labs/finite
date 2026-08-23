# Installation and updates

Purplefin can replace the image on an existing bootc system or be installed
with its graphical Anaconda ISO.

## Choose a foundation and home profile

Common published tags are:

| Tag | Target |
| --- | --- |
| `bluefin-generic` (`latest`) | Standard Bluefin on generic x86-64 |
| `bluefin-dell-xps-9350-intel` | Standard Bluefin on Dell XPS 13 9350 |
| `bluefin-dx-generic` | Bluefin DX on generic x86-64 |
| `bluefin-dx-dell-xps-9350-intel` | Bluefin DX on Dell XPS 13 9350 |

Legacy role tags temporarily point at their compatible foundation. The role
itself is selected with Home Manager: `sales` and `executive` require Bluefin;
`developer`, `support`, `it`, and `trainer` require Bluefin DX. `dale` combines
every role and requires the Dell Bluefin DX foundation. `elad` combines every
role on generic Bluefin DX so none of the Dell IPU7/SVP7500 camera layer or its
associated kernel modules are present.

The generated catalog contains every profile and tag:

```bash
nix build .#generated
jq '.profiles | with_entries(.value = .value.tags)' \
  result/bootc/generated/profile-catalog.json
```

## Switch an existing bootc system

Replace `latest` with the selected profile tag:

```bash
run0 bootc switch ghcr.io/closure-labs/finite:latest
run0 systemctl reboot
```

Inspect the active and staged deployments:

```bash
bootc status
```

## Determinate Nix lifecycle

Purplefin first installs Fedora's supported `nix` and `nix-daemon` packages,
then runs the pinned Determinate Nix Installer. The immutable image build uses
a narrow adapter around Determinate's existing-Nix preflight while retaining
Fedora's native filesystem and sysusers contracts. Base-image builds require
Determinate Nix 3.21.9 or newer; the
installer may resolve a later stable runtime, but an older runtime fails the
image build before publication.

The Fedora `nix-filesystem` dependency supplies `/nix`; Purplefin does not
create that directory separately. Because bootc keeps the image root immutable
and `/nix` must be writable, first boot copies the image seed to persistent
`/var/home/nix` and bind-mounts it at `/nix` before the Nix daemon starts. Later
boots preserve that state, including installed packages and store paths.
The daemon and socket activation links live in the immutable systemd vendor
tree, so fresh installations start Nix without depending on an `/etc` merge.
This also restores activation after switching an existing bootc workstation
whose retained `/etc` state omitted older Nix enablement links.
Before binding the daemon sockets, Purplefin removes socket files retained in
persistent state by an older installation; store paths and profiles are left
untouched.

Determinate Nixd owns Nix upgrades after migration. Use the normal Determinate
Nix upgrade mechanism rather than upgrading the runtime through Fedora's Nix
packages. A bootc upgrade may update the seed used by new installations, but
never overwrites an existing `/var/home/nix`.

The pinned Determinate policy module and its upstream `nix.fc` file-context
source are verified as build inputs. The policy is installed before the Nix
state is restored and relabeled.

## Apply a Home Manager role

Run this as the existing desktop user after booting the compatible foundation:

```bash
nix run github:closure-labs/finite#home-switch -- \
  --profile sales --hardware generic-x86_64
```

The bootstrap records the canonical Purplefin flake as the update source. When
installing from a fork, local checkout, or pinned reference, pass the same
reference with `--source FLAKE`.

Home Manager owns the role applications and preferences, including NixGL
wrappers for graphical Nix packages. Bitwarden CLI and Desktop are installed
from Nix rather than baked into the image. The locked Devenv CLI is included
in the `developer`, `dale`, and `elad` profiles. Espanso remains available to the
`support`, `dale`, and `elad` profiles as a Wayland Nix package and user
service. The initial activation writes a standalone per-user flake under
`~/.config/home-manager`; it records the selected role, hardware, username,
and absolute home directory required by Home Manager. It pairs the chilled
Nixpkgs 26.05 series with Home Manager 26.05, while its Purplefin input uses the
canonical GitHub flake by default, so the source repository does not need to
exist on the deployed workstation. `nh` discovers this flake through an
explicit `path:` URI and selects its `homeConfigurations.$USER` output
automatically. Reapply the locked generation with `nh home switch`. Update only
the Purplefin input and activate it with:

```bash
nh home switch --update-input purplefin
```

For compatibility, Zsh provides `purplefin-home` as an alias for the
update-and-switch command.

## Generate a cloud-init NoCloud seed

Cloud-init is additive and does not create users, change networking, or replace
the installer hostname. Generate a seed for an account that the installer will
create:

```bash
nix run .#cloud-init -- \
  --profile support \
  --hardware generic-x86_64 \
  --user dale \
  --output result/cloud-init-support
```

Attach `seed.iso` from that directory as a NoCloud configuration drive. The
first boot activates the chosen Home Manager profile for that existing user.
Use `--flake` to select a fork or pinned flake URI.

## Install from ISO

1. Run the `Build and boot-test Purplefin installer ISO` workflow from `main`.
2. Select the profile to embed.
3. Download the `purplefin-<profile>-installer` workflow artifact.
4. Verify the checksums and GitHub attestation:

   ```bash
   sha256sum --check SHA256SUMS
   gh attestation verify purplefin-*.iso \
     --repo closure-labs/finite
   ```

5. Write the ISO to installation media, boot it, and complete the graphical
   installer.

The artifact also contains `installer-manifest.json` and `qemu-boot.log`. The
schema-v2 manifest records the ISO, source commit, Image Builder, minimal
Fedora bootc live-environment base, and Purplefin payload. Its
`embedded_reference` is the exact verified digest incorporated into the ISO;
`update_reference` is the mutable profile tag that the installed system tracks.

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
