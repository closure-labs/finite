# Changelog

All notable changes to Finite are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Development version: `0.8.3-dev`. The next stable release is 0.8.3.

### Changed

- Keep ISO payloads out of protected signing handoffs, authenticating native
  preparation and fetching original approved products once for publication.
- Bound checks snapshots by dependency generation, scope contract source inputs,
  filter health to main delivery events and install only missing documentation tools.

### Fixed

- Correlate publication retries with authenticated identities from reused native
  preparation, reporting the current attempt's status and failing phase.
- Recover decision provenance from a bounded native PR inventory when transient
  commit-association API failures exhaust retries, preserving fresh authority checks.
- Revalidate release metadata and reconcile drafts by their confirmed IDs so
  cached inventories cannot be mistaken for conflicting release payloads.

## [0.8.3-dev] - 2026-10-21

Prepare a new development pair after the published `0.8.1` stable pair. The
unpublished `0.8.2-dev` payload, version reservation and recovery history remain
bound to their original products.

### Changed

- Pin the default Foundation source to published v0.3.0, including its matching
  dependency graph and source metadata. New profiles use schema 3; existing
  personal consumers retain their own source locks and update workflow.
- Negotiate fresh-login and seed profile formats from the bundled Foundation
  catalog. Schema-3 sources enable Personal roles, optional capabilities and
  independent host selections; seeds share Foundation's pure validator and keep
  the requested target identity. Existing saved profiles and source pins remain.
- Reject root before `ujust update` starts maintenance, and stop before Foundation
  when an upstream OS, Flatpak or Brew update command fails. Retain Bluefin's
  Just recipe, intentional skips and Foundation's staged update/recovery.
- Preserve saved Home Manager selections on first-login failure, gate unsupported
  schemas before initialization, and derive classified role choices from the
  Foundation catalog. Keep schema-2 seed generation and existing applications.
- Preserve Foundation role classification through the typed Home Manager catalog,
  including compatibility with older unclassified catalogs.
- Permit a new development version to follow the latest earlier stable pair
  without reusing an already reserved development version. An incomplete newer
  stable pair still blocks preparation.

### Fixed

- Require both Nix daemon sockets before first-login initialization.
- Recover interrupted asset uploads through remote reconciliation, stage both
  release inventories before publication and refresh approval at commit time.
- Bound archive transport retries, retain product bytes once per execution
  handoff and report the publisher's actual state in delivery health.

## [0.8.2-dev] - 2026-10-21

This is a development prerelease of both active images. It follows the
published `0.8.1` pair and retains the same qualification, security review and
protected signing requirements as stable releases.

### Changed

- Consume the Home Manager implementation and catalog from Foundation through
  an immutable source pin, replacing Finite's copied implementation.
- Keep personal configurations independent of OS updates. Explicit `ujust update`
  runs also build and apply published Foundation releases as the desktop user.
- Track published stable releases in new personal consumers through
  `latest-release`, supporting `nh home switch -u` while retaining exact lock pins.
- Provide staged migration, bounded builds, backups, activation rollback and
  clickable release notifications while preserving personal modules and sources.
- Require authenticated human security decisions and coordinate both image
  releases through one immutable, resumable release proposal.
- Prepare a paired development prerelease after each successful stable paired
  release, beginning with a reviewed PR for the next patch's `-dev` version.
  Prereleases do not become GitHub's latest release.
- Run targeted premerge encrypted Secure Boot VM validation for boot, installer,
  SELinux and qualification-harness changes. Report delivery and decision health
  independently and retry bounded transient GitHub metadata failures.

### Fixed

- Wait for the Nix daemon before starting display-manager and user sessions.
- Reconcile Wi-Fi power policy on power-source and NetworkManager events,
  coalescing updates through one systemd service.
- Relabel existing GDM state recursively while preserving ownership and modes.
  Qualify absent, directory and DynamicUser symlink layouts in isolated fixtures.
- Resolve abbreviated local Docker image IDs before premerge VM validation.
- Reconcile complete native security snapshots and skip decision collection for
  builds without image work. Initialize journals through the canonical repository
  API endpoint.

## [0.8.1] - 2026-10-15

### Changed

- Retain Bluefin and Bluefin-DX kernels, ZFS and other upstream modules together
  instead of replacing kernels or directly removing module packages. Verify
  inherited kernel/module payloads before and after Finite additions.
- Reduce active variants to `finite` and `finite-dev`; retire Next kernels,
  variants and kernel-update automation. Existing published Next releases remain
  historical artifacts.
- Preserve upstream authselect profiles and enabled features when adding
  supported Finite authentication features.
- Enable authenticated inventory and whole-qualification reuse in production CI
  after hosted measurements on the new Bluefin-based images. Inventory reuse
  saved a median 6m55s for Finite and 13m30s for Finite Dev per eligible hit.
  Whole-qualification reuse saved 30m29s and 32m21s respectively, reducing its
  measured critical-path service time by 93.1% and 93.6%.
- Keep fresh vulnerability database updates, scans and current security policy
  evaluation when reusing inventory. Qualification reuse requires matching image,
  predecessor, source and qualification context within its original 24-hour window.
  Production hit rate remains unmeasured; these are per-hit savings. Automatic
  Cachix writing and database transport remain disabled pending their own evidence.

### Fixed

- Use `finite` and `finite-dev` consistently for active recipe/profile names,
  image labels and CI jobs. Installation images are `finite.iso` and
  `finite-dev.iso`; Bluefin and Bluefin-DX remain the respective foundations.
- Name new channel releases `finite-0.8.1` and `finite-dev-0.8.1`, removing the
  duplicate `finite-` prefix used in v0.8.0. Historical release names and tags
  remain unchanged.

### Migration

- Next variants no longer receive new builds, security scans or qualification.
  Users of `finite-next` should move to `finite`, and users of `finite-dev-next`
  should move to `finite-dev`, following the signed-channel rebase instructions
  in the [v0.8.1 release plan](docs/v0.8.1-release-plan.md). The separate replacement
  kernel and IPU7 overlay are retired; hardware support follows the upstream
  Bluefin kernel and modules. Existing published Next releases remain available
  as historical artifacts.


## [0.8.0] - 2026-10-14

### Added

- Authenticated preservation and reuse of the original qualified installation
  ISO, with bounded retention and exact archive, image and installer bindings.
- Hosted cache and verification experiments with retained timing evidence.
- SecretSpec credentials and public CI options, using GitHub in CI and the
  password-store provider through devenv for local tasks.

### Changed

- Small CI jobs use measured cache defaults while retaining public binary-cache
  reads. Automatic Cachix publication remains disabled pending net savings.
- Cachix preparation defaults to declared tools, with optional proof seeding;
  tool realization and closure validation use strict batched associations.
- Image and qualification identities distinguish reviewed host-only tests from
  shipped payloads. Qualification also binds installer executable modes.
- Release preparation runs independently per channel and rejects tags that do
  not match the checkout version before downloading or signing assets.

### Fixed

- Bound SQLite checkpoint contention during ephemeral CI cache startup.
- Recognize a disk-unlock prompt interrupted by kernel serial output without
  weakening private passphrase handling or VM deadlines.

## [0.7.0] - 2026-10-13

### Added

- Desktop qualification checks for encrypted-root installation, Secure Boot,
  SELinux enforcement, signed upgrades and rollback before channel promotion.
- Release evidence that ties the image, installer, signatures and security
  review to an exact image digest.

### Changed

- Bluefin updates are checked regularly and failed channel updates are retried
  against the approved upstream image.
- Channels qualify independently, allowing standard Finite to ship without
  waiting for Next or development images.
- Vulnerability decisions use reviewed evidence of Critical impact on supported
  desktop use. Scanner matches alone do not establish exploitability; unresolved
  advisories remain documented risks.
- Shared command-line tools use the supported Homebrew integration, while Nix
  and Home Manager continue to manage the desktop configuration and applications.

### Fixed

- Home Manager template upgrades preserve the user's flake entry point and
  dependency lock, keeping custom inputs available to preserved modules.
- Restore the Nix GPU driver link after the persistent store mounts at boot,
  fixing Ghostty and other Nix graphics applications after reboot.
- Correct SELinux labels for persistent Nix state and home directories, and
  avoid repeating completed Nix store relabeling on every boot.
- Retry transient Home Manager download failures and preserve the compatible
  Den dependency set used by standalone home configurations.
- Restore signed image publication and authenticated reuse of valid security
  evidence after isolated signing and registry authentication failures.
- Recognize the container engine's explicit missing-signature rejection during
  upgrade qualification and retain useful diagnostics when validation fails.

### Removed

- Host ZFS support, including its kernel modules. Workstations use the supported
  Btrfs storage path; ZFS-dependent workloads need a separate environment.
- Optional virtual-camera modules from generic profiles so their availability
  no longer delays signed kernel security updates. Physical camera support is
  separate from this virtual-camera feature.

### Security

- Apply targeted package and signed kernel updates while preserving approved
  publishers, protected boot components and package ownership checks.
- Isolate image signing from builders and scanners, verify the signing key
  against the committed public key, and require exact-digest boot qualification
  before updating public channel tags.

## [0.6.0] - 2026-09-06

### Added

- Four handwritten BlueBuild recipes for Bluefin and Bluefin DX, each with
  generic and pinned next-kernel variants.
- On-demand signed-image ISO generation with recorded digests and checksums,
  plus hosted UEFI installation, update and rollback tests.
- A task-oriented README and guides for installation, app selection,
  customization, updates, troubleshooting and development.
- Per-user package selection through `finite-configure` for Hack Nerd Font,
  Herdr, Jujutsu, OpenCode and uv.
- A preserved `customize.nix` module for additional Nix packages, Flatpaks and
  Home Manager settings, plus a package-provider status report.

### Changed

- Image builds use the pinned BlueBuild Action and CLI, explicit update channels,
  Cosign key-pair signatures and final-image bootability checks. Each successful
  profile publishes independently.
- Nix stages the Home Manager template/catalog and pinned Determinate/kernel
  assets. Home Manager composes the user's roles, packages and hardware settings.
- The `next` and `dev-next` channels provide Fedora's signed 7.2 kernel and
  in-tree camera modules. The Dell display policy follows the user's Home
  Manager hardware selection.
- The base Nix environment includes Firefox, Bitwarden, LibreOffice, Nextcloud,
  Element, VLC and Thunderbird. Developers receive VSCodium.
- Nix supplies the primary command-line environment, with pinned chilled and
  weekly package inputs and existing Homebrew integrations available alongside it.
- Hosted Nix builds use four jobs with one core per derivation. Development
  examples bound local builds to one job and one core.
- Nix substitutions use the Finite-owned `finite-os.cachix.org` cache.

### Fixed

- Home Manager's non-NixOS GPU integration provides a persistent driver setup
  for Nix graphical applications.
- System-wide input permissions support Espanso in graphical sessions.
- Firefox uses PipeWire camera capture on Dell IPU7 systems, preserving the
  working microphone stream during WebRTC calls.
- The pinned installer completes Anaconda shutdown and finalizes the physical
  root configuration for successful composefs remounting.
- Nix daemon startup waits for persistent state and SELinux initialization.
- Bitwarden Desktop can use the image's Polkit action for PAM-backed unlocking.
- GNOME launches the customized Ghostty executable directly, and Vates Notes
  and Grist advertise their application roles correctly.
- Trusted dependency updates verify the pull-request author, revision and file
  scope before enabling merge-queue validation.

## [0.5.0] - 2026-08-26

### Added

- Enforcing SELinux support for installed Finite systems, including an offline
  target-policy relabel of installer-created account state in `/etc` and
  `/var/home` before the first boot.
- Hash-pinned Determinate Nix on Fedora 44, bootstrapped through Fedora's native
  Nix package contract and delivered with its SELinux policy, file contexts,
  immutable systemd units, and persistent `/nix` state.
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
- Replaced the legacy installer stack with Project Bluefin's pinned
  `dakota-iso` and `bootc-installer` architecture. Bluefin targets retain GRUB2
  and the live environment boots from an OSBuild Image Builder GRUB2 ISO.
- Installer builds now reuse a signed live seed per foundation and inject the
  selected profile recipe and verified offline payload after that seed boundary.
- Replaced Dakota's custom OCI archive and ISO assembly with Image Builder's
  direct containers-storage payload embedding and `bootc-generic-iso` pipeline.
- Ordered Determinate Nix policy installation, persistent-state seeding, the
  `/nix` bind mount, daemon sockets, and first-login setup as one bootc-safe
  lifecycle without early-boot systemd dependency cycles.

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
- Installer-changing pull requests and merge groups now run the native
  unattended JSON recipe, validate Project Bluefin's three-partition GRUB2
  layout, and boot the installed image with fresh OVMF variables before merge.
- Installer failures emit machine-readable serial markers so CI stops promptly
  and retains focused seed, ISO assembly, installation, partition, and boot logs.
- Installer-created users and homes receive the installed deployment's exact
  SELinux labels, allowing D-Bus, cloud-init, and the graphical session to start
  normally on the first enforcing boot.
- Determinate Nix sockets now activate only after policy, state, and `/nix` are
  ready; stale vendor enablement and immutable-root tmpfiles errors no longer
  race the daemon or first-login configuration.

### Security

- Profile import rejects undeclared fields, malicious source values, malformed
  identities, duplicate or unknown roles, unsupported foundation/hardware
  pairs, and running-image mismatches.
- Installed-system validation requires SELinux Enforcing, correct account and
  home contexts, the expected signed source and exact OSTree deployment, and a
  working pinned Determinate Nix daemon over the persistent `/nix` mount.
- Cachix configuration and proof publication are centralized, with a
  repository-wide contract rejecting every active former-name reference.

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

[Unreleased]: https://github.com/closure-labs/finite/compare/finite-0.8.1...HEAD
[0.8.1]: https://github.com/closure-labs/finite/releases/tag/finite-0.8.1
[0.8.0]: https://github.com/closure-labs/finite/releases/tag/finite-finite-0.8.0
[0.7.0]: https://github.com/closure-labs/finite/compare/v0.6.0...finite-finite-0.7.0
[0.6.0]: https://github.com/closure-labs/finite/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/closure-labs/finite/compare/v0.3.0...v0.5.0
[0.3.0]: https://github.com/closure-labs/finite/compare/v0.2.4...v0.3.0
[0.2.4]: https://github.com/closure-labs/finite/releases/tag/v0.2.4
[0.2.3]: https://github.com/closure-labs/finite/releases/tag/v0.2.3
[0.2.2]: https://github.com/closure-labs/finite/releases/tag/v0.2.2
[0.2.1]: https://github.com/closure-labs/finite/releases/tag/v0.2.1
[0.2.0]: https://github.com/closure-labs/finite/releases/tag/v0.2.0
