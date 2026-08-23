# Changelog

All notable changes to Finite are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-08-22

### Added

- Native `home-bluefin` and `home-bluefin-dx` templates that compose any subset
  of the Developer, Sales, Trainer, Support, Executive, and IT role aspects.
- `finite-home-profile` and `finite-home-bootstrap` applications for validated
  YAML provisioning, account discovery, normalized JSON state, locked
  standalone flakes, build-before-activation, and generic legacy JSON import.
- A per-user first-login Zenity checklist and `finite-configure` command with
  current-role preselection, base-only configuration, cancellation, graphical
  errors, and retry behavior.
- Explicit foundation and hardware metadata plus schema-2 Home Manager catalogs
  covering both foundations, both hardware targets, and every role.

### Changed

- Renamed the complete active product to Finite, including Nix
  namespaces, commands, environment variables, OCI labels, runtime paths,
  systemd units, installer assets, CI, release automation, tests, and docs.
- Replaced eight fixed Home Manager presets with Den-native standalone homes
  composed from the Finite base, selected hardware, and selected role aspects.
- Reduced published images to four foundation-and-hardware combinations;
  per-user roles no longer create image tags.
- Updated rEFInd, Plymouth, GDM, and shared image branding to the Finite mark.
- Cloud-init now writes a YAML Home Manager seed for first-login import instead
  of invoking a named profile.

### Removed

- Former product command aliases, paths, OCI fallbacks, compatibility shims,
  fixed named-profile APIs, and production use of Den's internal aspect
  resolver.

### Fixed

- Bootstrap writes deployed files only after its temporary standalone flake is
  locked and its activation package builds successfully.
- Complete Home Manager composition validation is evaluation-only in the normal
  check graph, avoiding accidental realization of every large role closure on
  developer workstations.

### Security

- Profile import rejects undeclared fields, malicious source values, malformed
  identities, duplicate or unknown roles, unsupported foundation/hardware
  pairs, and running-image mismatches.
- The legacy external Cachix endpoint and signing key are centralized as the
  only permitted former-name exception, with a repository-wide rename contract.

## [0.3.0] - 2026-08-20

### Added

- A schema-validated CI plan and aggregate Nix check package that make the
  complete repository validation graph explicit and locally reproducible.

### Changed

- CI preparation now runs through declared devenv tasks and focused Nix
  applications for checks, gates, releases, publishing, and lock updates.
- Hosted workflows use the repository's pinned Nix environments while retaining
  Cachix and isolating lightweight tasks from unrelated package realizations.

### Fixed

- Fresh CI runners explicitly realize every declared flake check before the
  no-build verification pass, preventing cache-only proof paths from breaking
  post-merge builds.
- Merge-group and path classification now fail safely when the compared source
  range cannot be established reliably.

### Security

- CI plans are strictly schema-validated, publication is serialized, and
  protected merge-group ancestry is verified before build decisions are trusted.

## [0.2.4] - 2026-08-20

### Added

- Four minimal Bluefin and Bluefin DX foundations for generic and Dell XPS 13
  9350 hardware, plus eight independently selectable Home Manager role profiles.
- NixGL-wrapped graphical applications, declarative per-user Flatpaks, and a
  Nix-managed Espanso user service for the support and Dale profiles.
- A NoCloud seed generator that applies a compatible Home Manager profile to
  an existing installer-created user without managing users or networking.
- The native Fedora Nix package bootstrap followed by the pinned Determinate
  installer, including its SELinux policy and file-context inputs.

### Changed

- Developer, support, IT, trainer, and Dale environments now target Bluefin DX;
  sales and executive environments target standard Bluefin.
- The Dell-only Dale profile now composes every role into one Bluefin DX user
  environment.
- The Elad profile composes every role on generic Bluefin DX without the Dell
  IPU7/SVP7500 camera components or associated custom kernel modules.
- Bitwarden CLI, Bitwarden Desktop, developer tools, and role applications are
  delivered through Nix/Home Manager instead of custom image layers or Homebrew.
- Image generation now preserves each signed Bluefin upstream as the foundation
  and limits Finite image changes to boot-critical integration and proven
  Dell hardware support.

### Removed

- The independently managed RPM mechanism and its Tailscale override; Finite
  now inherits the complete upstream Bluefin package set, including Tailscale.
- Image-baked Espanso, Bitwarden, role Flatpak manifests, Homebrew bundle
  automation, and role-specific image scripts.

### Fixed

- Installer blueprints retain canonical and legacy profile tag aliases so
  existing generic installation requests resolve to the correct Bluefin image.
- Dell camera builds bypass inherited ccache state and include Dracut live-boot
  modules while rebuilding initramfs on both Bluefin and Bluefin DX.

### Security

- Determinate Nix installer and SELinux policy inputs are hash-pinned, and the
  installed runtime is checked against the repository's minimum supported
  Determinate version.

## [0.2.3] - 2026-08-18

### Added

- Flake applications for pinned Syft generation, normalized SPDX validation,
  and verified software bill of materials attestation extraction.

### Changed

- Software bill of materials generation now runs in an ordered publication graph, allowing
  parent and descendant image builds to finish without waiting for scans.

### Fixed

- Release software bill of materials assets are extracted from the verified GitHub attestation for
  each immutable image digest instead of a parallel unsigned artifact.
- Installer payload validation now requires the software bill of materials signer workflow that
  actually publishes SPDX attestations.
- Image signatures and GitHub attestations retry transient transparency-log
  failures, and reused images avoid duplicate signatures and provenance.

### Removed

- The duplicate unsigned GHCR software bill of materials cache package and its cleanup path.

### Security

- Reused software bills of materials must match the image digest, source commit, predicate type, and
  pinned signer workflow before they can be published or released.

## [0.2.2] - 2026-08-18

### Added

- Typed, architecture-specific OCI locks for Bluefin and OSBuild Image Builder,
  with Nix applications for verification and atomic updates.
- Per-domain Nix workflow toolsets and a Statix validation proof.

### Changed

- GitHub workflows now keep security orchestration in YAML while using locked
  Nix tools for OCI, CI, installer, release, and maintenance operations.
- Profile, source, and repository modules now live in named dendritic
  subtrees; Home Manager profile data no longer relies on `extraSpecialArgs`.
- Generated build contracts are consumed directly from the Nix store, and CI
  derives its cache-proof list from the evaluated check graph.
- The generated profile catalog uses schema 3 for the typed OCI source model.
- Pull requests and merge groups now validate profiles in four balanced shards,
  loading the verified Bluefin digest once per runner before building and
  rechunking each assigned profile.

### Fixed

- Nix workflow toolsets now use a lower profile priority so runner-provided
  Buildah and Podman retain their supported user-namespace integration.
- Trusted release updates approve gated validation runs when required and clean
  generated manifests, notes, and software bills of materials before preparing the next development
  version.

### Removed

- The unused npins container archive hash and worktree artifact-export path.
- Dedicated ORAS and Cosign setup actions in image and release jobs.

### Security

- Bluefin and Image Builder transports are bound to architecture-specific OCI
  manifest digests; Bluefin loads also verify the committed Cosign issuer and
  identity before the exact digest enters container storage.
- Candidate sharding retains read-only registry permissions, `--pull=never`
  builds, independent image cleanup, and the existing signing, provenance, and
  SPDX attestation boundaries.

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
- Simplified the project guides around running Finite, building with Nix,
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
- A graphical Anaconda installer that embeds a verified Finite digest,
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
  Buildah layers and digest-bound software bill of materials documents are reused across matching
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
  provenance, compact SPDX software bill of materials attestations, immutable release tags, and
  digest manifests with per-profile software bill of materials assets.
- The required `CI gate` now validates repository policy, selected image and
  installer jobs, merge candidates, and trusted dependency-update automation.

[Unreleased]: https://github.com/closure-labs/finite/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/closure-labs/finite/compare/v0.3.0...v0.5.0
[0.3.0]: https://github.com/closure-labs/finite/compare/v0.2.4...v0.3.0
[0.2.4]: https://github.com/closure-labs/finite/releases/tag/v0.2.4
[0.2.3]: https://github.com/closure-labs/finite/releases/tag/v0.2.3
[0.2.2]: https://github.com/closure-labs/finite/releases/tag/v0.2.2
[0.2.1]: https://github.com/closure-labs/finite/releases/tag/v0.2.1
[0.2.0]: https://github.com/closure-labs/finite/releases/tag/v0.2.0
