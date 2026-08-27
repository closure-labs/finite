# Finite technical documentation

The project README is the short introduction. This directory is the reference
for installing, configuring, developing, and operating Finite.

## Start here

| Goal | Guide | What it covers |
| --- | --- | --- |
| Install or update a workstation | [Installation and updates](installation.md) | Image tags, bootc switching and rollback, first login, provisioning, ISO verification, and the Determinate Nix lifecycle |
| Configure a user environment | [Foundations, hardware, and roles](configuration.md) | Profile schema, Home Manager bootstrap, templates, compatibility, and the domain catalog |
| Diagnose a problem | [Troubleshooting](troubleshooting.md) | Deployment state, user services, image builds, the network installer, and hardware diagnostics |

## Hardware reference

- [Dell XPS 13 9350](dell-xps-9350.md) documents the hardware-specific image,
  boot presentation, authentication, battery, display, power, and camera
  behavior.
- [Dell XPS 13 9350 Secure Boot](dell-xps-9350-secure-boot.md) records the trust
  boundary between the signed kernel and external camera modules.

## Engineering reference

- [Development](development.md) covers the pinned Nix shell, repository layout,
  generated catalogs, focused checks, image applications, and brand assets.
- [CI and releases](ci-and-releases.md) describes change classification,
  sharded candidate validation, installer caching, attestations, trusted update
  automation, promotion, and release controls.

## Project records

- [Changelog](../CHANGELOG.md) records user-visible changes by release.
- [Repository security policy](ci-and-releases.md#repository-security-policy)
  explains the checked-in GitHub Actions, token, scanning, and environment
  settings and how to audit them.

Documentation should explain behavior and interfaces; the Nix modules,
schemas, tests, and checked-in GitHub policy remain the executable source of
truth.
