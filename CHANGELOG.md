# Changelog

All notable changes to Purplefin are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.1] - 2026-08-17

### Added

- Flake applications for repository validation, generated artifacts,
  image planning and builds, installer delivery, upstream verification, and
  selective workstation cache publication.
- An `npins` source lock and trusted update workflow for the signed
  Bluefin Stable architecture, tag, digest, and fixed-output metadata.

### Changed

- Reorganized the repository around typed Den profiles and feature-first
  aspects that colocate declarations, build steps, payloads, manifests, Home
  Manager modules, and focused tests.
- Made Nix the repository control plane for the profile graph, build contracts,
  generated catalogs, installer Blueprints, checks, and delivery operations.
- Consolidated CI on one pinned Nix and Cachix setup, one 13-check validation
  entrypoint, per-check filesets, and event classification from actual changed
  paths.
- Simplified the project guides around running Purplefin, building with Nix,
  customizing profiles, operating CI and releases, and troubleshooting.

### Fixed

- Restored executable bootc builder inputs and made image finalization consume
  the generated profile catalog contract.
- Made GitHub-hosted image builds enter Podman's supported user namespace
  before Skopeo streams the verified upstream image into container storage.

### Security

- Bluefin transport now verifies the pinned Cosign identity and immutable
  digest before loading the exact image used by Buildah.
- Cachix now restores and explicitly publishes reference-free check proofs
  behind a 1 MiB closure guard, with protected and same-repository events
  receiving scoped write access.

## [0.2.0] - 2026-08-17

### Added

- Twelve named bootc images composed from a common Bluefin foundation, reusable
  role aspects, and generic or Dell XPS 13 9350 hardware profiles.
- A Nix and Den profile graph that generates the ordered image matrix, semantic
  build inputs, Home Manager configurations, profile catalog, and OSBuild
  Blueprints.
- A graphical Anaconda installer that embeds a verified Purplefin digest,
  smoke-boots in QEMU, and publishes an attested component manifest.
- Dell XPS 13 9350 support for the IPU7 camera, lid-aware privilege
  authentication, battery charge thresholds, TuneD power profiles, automatic
  display refresh rates, and rEFInd theming.
- A shared hardware-security baseline with fingerprint authentication,
  PAM U2F/FIDO2, YubiKey management, and smart-card services.

### Changed

- Image builds now resolve immutable upstream and parent digests, build the
  dependency graph parent-first, rechunk each image, and promote channel tags
  as aliases of one published digest.
- CI now selects profiles from semantic source, base, RPM, and parent changes;
  Buildah layers and digest-bound SBOM documents are reused across matching
  builds.
- The common workstation foundation now includes Podman Machine, QEMU disk
  tooling, Homebrew packages, shared Flatpaks, and a reusable DevOps component
  for development and support profiles.
- Bitwarden and Nextcloud desktop delivery now use verified system Flatpaks,
  with ordered first-boot migration and a packaged native Bitwarden CLI.
- Repository formatting now runs through the flake-pinned treefmt environment,
  and Determinate manages flake-input refresh pull requests.

### Fixed

- Stabilized the Dell IPU7 pipeline with pinned SVP7500 modules, firmware
  inclusion, OV02C10 gain and color tuning, PipeWire camera discovery, and
  filtering of raw capture endpoints.
- Made installer builds reproducible across hosted runners with single-layer
  environment construction, normalized image identifiers, deterministic output
  ownership, shared caching, and diagnostic artifacts.
- Preserved Bluefin's Tailscale integration while independently updating its
  installed RPM alongside Espanso.

### Security

- Published images now include keyless Cosign signatures, GitHub build
  provenance, compact SPDX SBOM attestations, immutable release tags, and
  digest manifests with per-profile SBOM assets.
- The required `CI gate` now validates repository policy, selected image and
  installer jobs, merge candidates, and trusted dependency-update automation.

[Unreleased]: https://github.com/declarative-dale/purplefin/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/declarative-dale/purplefin/releases/tag/v0.2.1
[0.2.0]: https://github.com/declarative-dale/purplefin/releases/tag/v0.2.0
