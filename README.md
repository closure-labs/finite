# Purplefin

Purplefin turns a typed Nix profile graph into signed, updateable
[bootc](https://bootc-dev.github.io/bootc/) workstation images based on
[Bluefin Stable](https://projectbluefin.io/).

You get twelve ready-to-run workstation profiles, reproducible local builds,
a graphical installer, verified updates, and signed release artifacts with
provenance and SPDX software bill of materials attestations.

## Run Purplefin

On an existing bootc system, switch to the generic workstation image:

```bash
run0 bootc switch ghcr.io/declarative-dale/purplefin:latest
run0 systemctl reboot
```

Stay current with:

```bash
run0 bootc upgrade
run0 systemctl reboot
```

For a fresh machine, follow the [graphical installation guide](docs/installation.md).

## Build Purplefin with Nix

Install Nix with Flakes enabled and rootless Podman, then run:

```bash
git clone https://github.com/declarative-dale/purplefin.git
cd purplefin
nix run .#image-build -- base-generic localhost/purplefin:base-generic
```

Format and validate the complete repository with the pinned toolchain:

```bash
nix develop
nix fmt
nix run .#ci
```

## Choose a profile

| Profile | Use it for |
| --- | --- |
| `latest` | A generic base workstation |
| `developer-generic` | Software development on generic x86-64 hardware |
| `support-generic` | Support and operations on generic x86-64 hardware |
| `dale` | Sales, training, and support on a Dell XPS 13 9350 |

List every generated profile and published tag with:

```bash
nix build .#generated
jq '.profiles | with_entries(.value = .value.tags)' \
  result/bootc/generated/profile-catalog.json
```

## Learn more

- [Documentation guide](docs/README.md)
- [Changelog](CHANGELOG.md)
