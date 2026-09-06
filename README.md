# <img src="files/system/usr/share/finite/finite-logo.png" width="56" height="56" align="middle" alt=""> Finite

A GNOME desktop built on Bluefin, with your apps and personal settings managed
by Nix and Home Manager. Choose the environment that fits your work, add your
own packages, and keep your configuration across system updates.

## Get started

1. **Choose an image.** Start with `bluefin-generic` for everyday use, or
   `bluefin-dx-generic` for Bluefin's developer environment. The `next` variants
   provide a pinned newer Fedora kernel for hardware that needs it.
2. **Install Finite.** Follow the [installation guide](docs/installation.md) to
   get a verified ISO and install it. Every image runs the Bluefin GNOME desktop.
3. **Set up your apps.** At first login, select your roles and optional packages.
   Run `finite-configure` whenever you want to change those choices.

| Your environment | Update channel |
| --- | --- |
| Bluefin | `bluefin-generic` (also `latest`) |
| Bluefin with the next kernel | `next` |
| Bluefin DX | `bluefin-dx-generic` |
| Bluefin DX with the next kernel | `dev-next` |

Images are published at `ghcr.io/closure-labs/finite`. For the Dell XPS 13 9350,
see the [hardware guide](docs/dell-xps-9350.md).

## Make it yours

Finite includes everyday desktop apps and command-line tools. Choose any mix of
Developer, Sales, Trainer, Support, Executive and IT roles. Optional packages
include Hack Nerd Font, Herdr, Jujutsu, OpenCode and uv.

For your own packages and settings, edit
`~/.config/home-manager/customize.nix`, then apply them with:

```bash
nh home switch
```

Your customization file persists when Finite refreshes the managed
configuration. See [Configure your environment](docs/configuration.md) for
examples, GPU setup and standalone Home Manager templates.

## Keep it up to date

System updates arrive as signed images. Nix and Home Manager manage your user
environment. The [update guide](docs/installation.md#update-your-system) covers
both, including returning to a previous system deployment.

## Find your way around

- [Install and update](docs/installation.md)
- [Configure your environment](docs/configuration.md)
- [Troubleshoot a problem](docs/troubleshooting.md)
- [Develop Finite](docs/development.md)
- [What's new in 0.6.0](CHANGELOG.md#060---2026-09-06)

BlueBuild recipes define the four images. Nix stages the Home Manager template
and pinned installation assets. The [documentation index](docs/README.md) links
to the build, signing, release and hardware references.
