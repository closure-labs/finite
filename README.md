# Finite

Finite is a signed, updateable Linux workstation built on Bluefin and Bluefin
DX. The operating-system image supplies a stable foundation; each user chooses
their own Home Manager roles at first login.

## Choose an image

| Image tag | Foundation | Hardware |
| --- | --- | --- |
| `latest` or `bluefin-generic` | Bluefin | Generic x86-64 |
| `bluefin-dell-xps-9350-intel` | Bluefin | Dell XPS 13 9350 |
| `bluefin-dx-generic` | Bluefin DX | Generic x86-64 |
| `bluefin-dx-dell-xps-9350-intel` | Bluefin DX | Dell XPS 13 9350 |

Bluefin DX includes the developer-oriented foundation. User roles are separate
from image tags: Developer, Sales, Trainer, Support, Executive, and IT can be
combined on either foundation. Selecting no roles gives you the shared base
environment.

## Install or switch

To switch an existing bootc workstation to generic Finite:

```console
run0 bootc switch ghcr.io/closure-labs/finite:latest
run0 systemctl reboot
```

Replace `latest` with another tag from the table when needed. For a new machine
or installer ISO, follow the [installation guide](docs/installation.md). Finite
uses Project Bluefin's native graphical bootc installer, keeps GRUB2 on
installed Bluefin systems, and embeds the verified image for offline setup.

## Complete first login

After the graphical session opens, Finite shows a role checklist. Choose any
combination and select **Configure**. It is valid to leave every role unchecked.

Finite then:

1. Discovers your username and home directory.
2. Confirms the running foundation and hardware.
3. Generates and locks a standalone flake in `~/.config/home-manager`.
4. Builds the complete Home Manager activation package.
5. Saves normalized state in `~/.config/finite/profile.json` and activates only
   after the build succeeds.

Canceling changes nothing, so the checklist returns at the next graphical
login. Run `finite-configure` later to reopen it with your current roles
selected.

## Create a standalone Home Manager configuration

Start from either native template:

```console
nix flake new -t github:closure-labs/finite#home-bluefin ./home
nix flake new -t github:closure-labs/finite#home-bluefin-dx ./home-dx
```

Generate and apply a YAML profile:

```console
nix run github:closure-labs/finite#home-profile -- \
  --foundation bluefin-dx \
  --hardware dell-xps-9350-intel \
  --roles developer,support \
  --format yaml >profile.yaml

nix run github:closure-labs/finite#home-bootstrap -- \
  --profile profile.yaml
```

Bootstrap rejects malformed data, unknown or duplicate roles, invalid account
identity, and profiles that do not match the running Finite image.

## Update and troubleshoot

```console
run0 bootc upgrade
run0 systemctl reboot
nh home switch --update-input finite
```

See [configuration](docs/configuration.md) for profiles and provisioning, or
[troubleshooting](docs/troubleshooting.md) for failed image, first-login, and
Home Manager operations.

## Develop Finite

```console
git clone git@github.com:closure-labs/finite.git
cd finite
nix develop
nix fmt
just check
```

Build one image locally:

```console
nix shell --accept-flake-config .#ci-image-build \
  -c finite-image-build bluefin-generic localhost/finite:bluefin-generic
```

The [development guide](docs/development.md) describes generated catalogs,
focused checks, image tools, and repository layout. Start with the
[documentation index](docs/README.md) for every guide.
