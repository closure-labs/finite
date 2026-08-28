# Finite technical documentation

The project README is the short introduction. This directory is the reference
for installing, configuring, developing, and operating Finite.

## Start here

| Goal | Guide | What it covers |
| --- | --- | --- |
| Install or update a workstation | [Installation and updates](installation.md) | Image tags, bootc switching and rollback, first login, provisioning, ISO verification, and the Determinate Nix lifecycle |
| Configure a user environment | [Foundations, hardware, roles, and packages](configuration.md) | Profile schema, Home Manager bootstrap, customization, graphical selection, templates, compatibility, and the domain catalog |
| Reduce Homebrew safely | [Staged Homebrew migration](homebrew-migration.md) | Bluefin-owned formulas, Nix replacements, fallback layers, and removal gates |
| Diagnose a problem | [Troubleshooting](troubleshooting.md) | Deployment state, user services, image builds, the network installer, and hardware diagnostics |

## Hardware reference

- [Dell XPS 13 9350](dell-xps-9350.md) documents the vendor-neutral next image,
  optional Home Manager display policy, and IPU7 camera checks.
- [Dell XPS 13 9350 Secure Boot](dell-xps-9350-secure-boot.md) records the Fedora
  7.2 in-tree module and signature contract.

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
