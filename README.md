# Purplefin

Purplefin is a signed, updateable [bootc](https://bootc-dev.github.io/bootc/)
workstation image based on [Bluefin Stable](https://projectbluefin.io/). Images
are published to `ghcr.io/declarative-dale/purplefin` with Cosign signatures,
build provenance, and SPDX SBOM attestations.

## Concepts

- **Aspect:** a reusable base, hardware, capability, or role feature under
  `modules/aspects/`.
- **Profile:** a complete image assembled by including aspects and parent
  profiles in the Den graph declared by `modules/profiles.nix`.
- **Flake:** the source of build plans, generated installer data, development
  tools, tests, and CI/CD applications.
- **Source pin:** the Bluefin stable OCI digest and Nix archive hash locked by
  `npins/sources.json` and included in the Den graph.
- **Published tag:** a movable name for a signed image digest. Examples include
  `latest`, `developer-generic`, `support-generic`, and `dale`.

## Quick start

On an existing bootc system, switch to the generic base profile and reboot:

```bash
run0 bootc switch ghcr.io/declarative-dale/purplefin:latest
run0 systemctl reboot
```

Install future updates with:

```bash
run0 bootc upgrade
run0 systemctl reboot
```

To inspect all profiles from a checkout:

```bash
nix build .#generated
jq '.profiles' result/bootc/generated/profile-catalog.json
```

For a fresh system, use the verified graphical ISO described in
[Installation](docs/installation.md).

## Development quick start

```bash
nix develop
nix fmt
nix flake check --print-build-logs
```

## Documentation

- [Installation and updates](docs/installation.md)
- [Profiles and advanced configuration](docs/configuration.md)
- [Development and local builds](docs/development.md)
- [CI, image publication, and releases](docs/ci-and-releases.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Dell XPS 13 9350 hardware behavior](docs/dell-xps-9350.md)
- [Dell XPS 13 9350 Secure Boot status](docs/dell-xps-9350-secure-boot.md)
- [Changelog](CHANGELOG.md)
