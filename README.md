# <img src="files/system/usr/share/finite/finite-logo.png" width="56" height="56" align="middle" alt=""> Finite

A Bluefin GNOME desktop you can make your own. Choose your apps and work tools,
manage personal settings with Nix and Home Manager, and carry your configuration
across system updates.

## Get started

1. **Choose an image.** Start with `finite` for everyday use, or
   `finite-dev` for Bluefin's developer environment.
2. **Install Finite.** Follow the [installation guide](docs/installation.md) to
   download and verify an ISO, then install it.
3. **Set up your apps.** At first login, select your roles and optional packages.
   Run `finite-configure` whenever you want to change those choices.

| Choose | Environment | Update channel |
| --- | --- | --- |
| Finite | Bluefin desktop | `finite` (also `latest`) |
| Finite Dev | Bluefin DX developer desktop | `finite-dev` |

Images are published at `ghcr.io/closure-labs/finite`. For a Dell XPS 13 9350,
use the [hardware guide](docs/dell-xps-9350.md) alongside installation.

## Make it yours

Finite includes everyday desktop apps and command-line tools. Choose any mix of
Developer, Sales, Trainer, Support, Executive and IT roles. Optional packages
include Hack Nerd Font, Herdr, Jujutsu, OpenCode and uv.

For your own packages and settings, edit
`~/.config/home-manager/customize.nix`, then apply them with:

```bash
nh home switch
```

Your environment uses published stable releases of
[Foundation](https://github.com/closure-labs/foundation), pinned in your personal
configuration. See [Configure your environment](docs/configuration.md) for
package examples, GPU setup and update controls.

## Keep it up to date

System updates arrive as signed images. `ujust update` also builds and applies
published Foundation releases for your user environment. The
[update guide](docs/installation.md#update-your-system) covers both, including
returning to a previous system deployment.

## Find your way around

- [Install and update](docs/installation.md)
- [Configure your environment](docs/configuration.md)
- [Troubleshoot a problem](docs/troubleshooting.md)
- [Develop Finite](docs/development.md)
- [What's new](CHANGELOG.md)

Explore the [documentation](docs/README.md) for hardware checks, developer
guides, security review and release operations.
