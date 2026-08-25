# Installation and updates

Finite publishes four foundation images:

| Tag | Foundation and hardware |
| --- | --- |
| `bluefin-generic` (`latest`) | Bluefin, generic x86-64 |
| `bluefin-dell-xps-9350-intel` | Bluefin, Dell XPS 13 9350 |
| `bluefin-dx-generic` | Bluefin DX, generic x86-64 |
| `bluefin-dx-dell-xps-9350-intel` | Bluefin DX, Dell XPS 13 9350 |

Roles are not image tags. Every combination of the six roles is selected per
user through Home Manager after the foundation boots.

Finite-branded rEFInd entries are installed by the Dell hardware image. All
four images display the Finite mark in the Plymouth splash after a boot entry
is selected.

## Switch an existing bootc system

```console
sudo bootc switch ghcr.io/closure-labs/finite:latest
sudo systemctl reboot
bootc status
```

Use another tag from the table when appropriate. Update or roll back with:

```console
sudo bootc upgrade
sudo systemctl reboot
# or
sudo bootc rollback
sudo systemctl reboot
```

## First graphical login

`finite-home-first-login.service` runs independently for every local graphical
user. If `~/.config/finite/profile.json` already exists it exits immediately.
Otherwise it imports `/etc/finite/home-profiles/$USER.yaml` without prompting,
or shows a Zenity checklist with all roles initially unchecked.

Choosing Configure with no roles creates the base-only environment. Canceling
or closing the dialog writes nothing, and the selector returns at the next
graphical login. Build or activation errors are shown graphically, recorded in
the user journal, and retried on a later login. Run `finite-configure` at any
time to change the selected roles; the running image remains authoritative for
foundation and hardware.

## Provision with cloud-init

Generate a NoCloud seed containing YAML for an installer-created account:

```console
nix run .#cloud-init -- \
  --foundation bluefin-dx \
  --hardware generic-x86_64 \
  --roles developer,support \
  --user dale \
  --output result/cloud-init-dale
```

Attach `seed.iso` as a NoCloud configuration drive. Cloud-init writes only
`/etc/finite/home-profiles/dale.yaml`; it does not invoke a named preset, create
users, replace networking, or change the installer hostname. First-login
validates and imports the seed.

## Bootstrap manually

```console
nix run github:closure-labs/finite#home-profile -- \
  --foundation bluefin-dx --hardware generic-x86_64 \
  --roles developer,support --format yaml >profile.yaml
nix run github:closure-labs/finite#home-bootstrap -- --profile profile.yaml
```

Bootstrap validates before writing, generates a remote-input lock, builds the
activation package, atomically replaces the managed files, and activates only
after the build succeeds. Later updates use:

```console
nh home switch --update-input finite
```

## Determinate Nix lifecycle

Finite installs Fedora's Nix filesystem and account contracts before applying
the pinned Determinate Nix installer and SELinux policy. `/nix` is backed by
persistent `/var/home/nix`; image updates never overwrite an existing store.
Determinate Nixd owns runtime upgrades. Finite removes only stale daemon socket
files before binding the persistent state.

## Install from ISO

1. Run the `Build and boot-test Finite installer ISO` workflow from `main`.
2. Select one of the four foundation profiles.
3. Download the `finite-<profile>-installer` artifact.
4. Verify it:

   ```console
   sha256sum --check SHA256SUMS
   gh attestation verify finite-*.iso --repo closure-labs/finite
   ```

5. Write the ISO to installation media and complete the graphical Finite installer.

The manifest records the immutable payload, signed live-seed identity, pinned
Project Bluefin installer inputs, source commit, and mutable update reference. See
[Troubleshooting](troubleshooting.md) for runtime and installer checks.
