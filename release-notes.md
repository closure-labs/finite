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
