# Configure your environment

Start with `finite-configure`. It opens the role and optional-package selectors,
shows your current choices, builds the selected environment, and activates it
after the build succeeds.

You can combine Developer, Sales, Trainer, Support, Executive and IT roles.
Optional packages include Hack Nerd Font, Herdr, Jujutsu, OpenCode and uv.
Every combination includes Finite's base desktop apps and command-line tools.

## Add packages and personal settings

Edit `~/.config/home-manager/customize.nix`. It is a Home Manager module, so you
can add Nix packages, Flatpaks and other settings together:

```nix
{pkgs, ...}: {
  home.packages = with pkgs; [jq];
  services.flatpak.packages = ["org.gimp.GIMP"];
}
```

Build your changes, then activate them:

```bash
nh home build
nh home switch
```

Lists merge with the Finite defaults. Finite preserves `customize.nix` and
`modules/local.nix`, along with your `flake.nix` and `flake.lock`, when it
refreshes the managed configuration.

Most packages come from the pinned chilled Nixpkgs input. For a package that
needs the weekly input, use its package set explicitly:

```nix
{inputs, pkgs, ...}: {
  home.packages = [
    inputs.nixpkgs-weekly.legacyPackages.${pkgs.stdenv.hostPlatform.system}.jq
  ];
}
```

See [Application sources](application-sources.md) for choosing package providers.

## Add custom flake inputs

Your `~/.config/home-manager/flake.nix` is yours to edit. Add dependencies to
its existing `inputs` attribute, for example:

```nix
inputs.nixpkgs-unstable.url = "github:NixOS/nixpkgs/nixos-unstable";
```

Then use the input from `customize.nix`:

```nix
{inputs, pkgs, ...}: {
  home.packages = [
    inputs.nixpkgs-unstable.legacyPackages.${pkgs.stdenv.hostPlatform.system}.hello
  ];
}
```

Lock the added input, build, and activate:

```bash
nix flake lock ~/.config/home-manager
nh home build
nh home switch
```

Finite already uses Den to compose the Home Manager modules and passes all
flake inputs to them. No additional flake framework is needed. Inputs are
declared in `flake.nix`; `customize.nix` consumes them. Non-flake sources can
use `flake = false` and Git sources may use authenticated SSH URLs. Store
credentials in your SSH agent or credential configuration, outside the flake.

Image upgrades refresh Finite's generated modules and assets while preserving
your flake entry point, `nixConfig`, customizations and complete dependency lock.
They do not update your dependency pins. Use
`nix flake update INPUT_NAME --flake ~/.config/home-manager` for an intentional
input update, then build before activating. Keep both `flake.nix` and
`flake.lock`; an incomplete pair
stops the upgrade with an error. The shipped defaults remain available under
`/usr/share/finite/home-manager-template/` for comparing future changes.

## Enable GPU access for Nix apps

After the first Home Manager activation, run its GPU setup command:

```bash
sudo "$(command -v non-nixos-gpu-setup)"
readlink /run/opengl-driver
```

The helper connects Nix applications to the graphics drivers and creates a
persistent tmpfiles rule and Nix garbage-collection root. Run it again when
Home Manager reports that the driver setup needs an update.

At boot, `finite-nix-gpu.service` recreates `/run/opengl-driver` after
`nix.mount` and before the display manager starts. This is necessary because
the regular early tmpfiles pass runs before Finite's persistent Nix store is
available. The service skips machines that have not run the GPU setup helper.

The supported path covers 64-bit Mesa on Intel, AMD and Nouveau. Systems using
proprietary NVIDIA or 32-bit graphics need additional integration.

## Your configuration files

| Location | Purpose |
| --- | --- |
| `~/.config/finite/profile.json` | Selected foundation, hardware, roles, packages and account |
| `~/.config/home-manager/` | Complete standalone Home Manager configuration and lock |
| `~/.config/home-manager/customize.nix` | Your additional packages and settings |
| `/usr/share/finite/profile.json` | Running image's foundation, hardware, channel and kernel |

The image selects the foundation: `bluefin` or `bluefin-dx`. Home Manager selects
compatible user hardware settings. On an XPS 13 9350, first login detects the
machine and selects the [Dell display policy](dell-xps-9350.md).

The standalone flake includes its Finite modules, assets, helper scripts and
pinned dependencies. It exports `homeConfigurations.<username>`, which `nh`
selects for your account. Update its inputs with
`nix flake update --flake ~/.config/home-manager`.

## Provision an environment

For scripted setup, provide YAML or JSON to
`/usr/libexec/finite/home-init --profile PROFILE`. For example:

```json
{
  "schema": 2,
  "foundation": "bluefin-dx",
  "hardware": "generic-x86_64",
  "packages": ["jj", "uv"],
  "roles": ["developer", "support"],
  "identity": {}
}
```

The initializer discovers the current account, validates the selected options
against the image, and builds a staged configuration. After success, it installs
the complete configuration and keeps a timestamped copy of the previous one.
An explicit identity must match the current account.

## Start from a template

Create a standalone configuration in a new directory:

```bash
nix flake new -t github:closure-labs/finite#home-manager my-home
```

The `home-bluefin` and `home-bluefin-dx` template names expose the same complete
template. Its local `profile.json` selects the foundation, hardware, roles,
packages and account. The image's first-login initializer supplies these values
when creating a workstation configuration.

For the implementation and catalog layout, see [Development](development.md).
