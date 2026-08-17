# Purplefin

Purplefin is a signed, updateable bootc operating-system image based on
[Bluefin Stable](https://projectbluefin.io/). It composes a common workstation
foundation with role and hardware profiles, then publishes the finished images
to `ghcr.io/declarative-dale/purplefin`.

Every published image includes provenance and an SPDX SBOM. The default image
provides Git, Micro, Podman Machine, QEMU disk tooling, Homebrew packages,
common Flatpaks, fingerprint authentication, FIDO2 support, YubiKey tooling,
and smart-card services.

## Choose an image

| Image tag | Intended system |
| --- | --- |
| `latest` | Base workstation on generic x86-64 hardware |
| `developer-generic` | Development workstation on generic x86-64 hardware |
| `support-generic` | Support workstation on generic x86-64 hardware |
| `dale` | Sales, training, and support workstation on a Dell XPS 13 9350 |

The generated
[profile catalog](bootc/generated/profile-catalog.json) lists every image,
role, hardware selection, parent, and published tag.

## Switch an existing bootc system

Choose a complete profile and reboot into it:

```bash
run0 bootc switch ghcr.io/declarative-dale/purplefin:latest
run0 systemctl reboot
```

Use the same tag for subsequent upgrades:

```bash
run0 bootc upgrade
run0 systemctl reboot
```

For a new machine, build or download the graphical Anaconda ISO described in
the [installer guide](installer/README.md).

## Develop

Enter the pinned development environment and run the repository checks:

```bash
nix develop
just check
nix flake check
```

The flake supplies the formatter, linters, test tools, generated profile data,
Home Manager activation packages, and OSBuild Blueprints.

## Read more

- [Changelog](CHANGELOG.md) summarizes the user-facing changes in each release.
- [Building and development](docs/building-and-development.md) covers local
  image builds, generated files, formatting, and validation.
- [Customizing profiles](docs/customizing.md) explains the Den graph, aspects,
  bootc modules, overlays, and Home Manager settings.
- [Nonstandard use cases](docs/nonstandard-use-cases.md) covers security-key
  enrollment, lid-closed work sessions, and package migrations.
- [Dell XPS 13 9350](docs/dell-xps-9350.md) documents authentication, battery,
  display, power, and IPU7 camera behavior.
- [Installer](installer/README.md) describes the verified Anaconda ISO build
  and its artifacts.
- [Builds and releases](docs/builds-and-releases.md) documents selective image
  builds, signatures, SBOMs, provenance, and release promotion.
- [CI and testing](docs/ci-objectives.md) and the
  [merge policy](docs/ci-merge-queue.md) describe the required gate and trusted
  update automation.
