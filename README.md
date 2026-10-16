# <img src="files/system/usr/share/finite/finite-logo.png" width="56" height="56" align="middle" alt=""> Finite

A GNOME desktop built on Bluefin, with your apps and personal settings managed
by Nix and Home Manager. Choose the environment that fits your work, add your
own packages, and keep your configuration across system updates.

## Get started

1. **Choose an image.** Start with `finite` for everyday use, or
   `finite-dev` for Bluefin's developer environment. Both preserve the kernel
   and modules supplied by their approved Bluefin base.
2. **Install Finite.** Follow the [installation guide](docs/installation.md) to
   get a verified ISO and install it. Every image runs the Bluefin GNOME desktop.
3. **Set up your apps.** At first login, select your roles and optional packages.
   Run `finite-configure` whenever you want to change those choices.

| Your environment | Update channel |
| --- | --- |
| Bluefin | `finite` (also `latest`) |
| Bluefin DX | `finite-dev` |

The former `finite-next` and `finite-dev-next` variants are retired. Their
published releases remain historical downloads; new builds and updates use the
two channels above.

Images are published at `ghcr.io/closure-labs/finite`. For the Dell XPS 13 9350,
see the [hardware guide](docs/dell-xps-9350.md). Camera, virtual-camera and
filesystem module providers remain as supplied by the approved upstream image.
Hardware support depends on that base and the installed kernel.

## Make it yours

Finite includes everyday desktop apps and command-line tools. Choose any mix of
Developer, Sales, Trainer, Support, Executive and IT roles. Optional packages
include Hack Nerd Font, Herdr, Jujutsu, OpenCode and uv.

For your own packages and settings, edit
`~/.config/home-manager/customize.nix`, then apply them with:

```bash
nh home switch
```

[Foundation](https://github.com/closure-labs/foundation) owns the shared Home
Manager modules. Your personal configuration tracks published stable releases,
with its exact version recorded in `flake.lock`. See
[Configure your environment](docs/configuration.md) for examples, GPU setup and
standalone Home Manager templates.

## Keep it up to date

System updates arrive as signed images. `ujust update` also builds and applies
published Foundation releases for your user environment. The [update guide](docs/installation.md#update-your-system) covers
both, including returning to a previous system deployment.

## Find your way around

- [Install and update](docs/installation.md)
- [Configure your environment](docs/configuration.md)
- [Troubleshoot a problem](docs/troubleshooting.md)
- [Develop Finite](docs/development.md)
- [What's new in 0.8.1](CHANGELOG.md#081---2026-10-15)

BlueBuild recipes define the two active images. Nix stages the Home Manager template
and pinned installation assets. The [documentation index](docs/README.md) links
to the build, signing, release and hardware references.
