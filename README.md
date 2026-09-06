# Finite

Finite combines Bluefin bootc images with Nix and Home Manager for applications
and user configuration. BlueBuild recipes are the image source of truth.

| Recipe | Foundation | Kernel | Image tags |
| --- | --- | --- | --- |
| `recipes/bluefin-generic.yml` | Bluefin stable | Inherited | `bluefin-generic`, `latest` |
| `recipes/bluefin-next.yml` | Bluefin stable | Pinned next | `next` |
| `recipes/bluefin-dx-generic.yml` | Bluefin DX stable | Inherited | `bluefin-dx-generic` |
| `recipes/bluefin-dx-next.yml` | Bluefin DX stable | Pinned next | `dev-next` |

All tags belong to `ghcr.io/closure-labs/finite`. Shared modules manage system
packages, authentication, vendor files, system services, branding and signing.
Nix produces only the staged template/catalog and pinned installation assets for
this build path. Generic builds omit next-kernel downloads.

Home Manager remains the primary application and user-configuration engine.
Existing roles, package selections, standalone templates, `customize.nix`,
Firefox camera policy, Dell display policy and user services retain their roles.
Nix packages come first; existing Flatpak and Homebrew exceptions remain.

See [installation](docs/installation.md), [configuration](docs/configuration.md),
[development](docs/development.md), [CI and publishing](docs/ci-and-releases.md),
and [troubleshooting](docs/troubleshooting.md).
