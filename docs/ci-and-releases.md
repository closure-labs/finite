# CI, publication, and releases

GitHub Actions selects work from the changed paths and the Nix-generated image
graph. The Flake supplies the check and build applications; workflows supply
events, permissions, runners, environments, attestations, and artifact upload.
Path classification treats renames as a deletion plus an addition, so moving a
build input into a documentation directory cannot hide its original impact.
Installer validation is selected only by the installer graph, generated profile
blueprints, or their pinned tools; image-only aspects and repository tests do
not rebuild the unchanged ISO.

Classification and planning cross the workflow boundary as one schema-versioned,
strictly validated JSON plan. `purplefin-ci-prepare` is the only workflow-facing
authority: it records whether the diff is trustworthy and the exact image,
software-bill-of-materials, promotion, and installer jobs required for the run.
Profile selection uses the generated
per-profile build-input fingerprints and parent graph: changed targets expand to
their descendants, while shard planning adds ancestors only as local build
dependencies. Publication additionally checks registry state, signatures,
provenance, RPM updates, and repair work before finalizing that lifecycle.

## Validation layers

| Layer | Runs when | Validates |
| --- | --- | --- |
| Repository | Every pull request and main build | Flake checks, generated data, source, tests, and workflows |
| Candidate images | Image inputs change | Selected profiles and descendants in four read-only, runner-local shards |
| Installer contract | Every pull request and main build | Nix wiring, generated Blueprints, rootfs contract, and smoke-test behavior |
| Installer image | Installer inputs change, a base payload is published, or on schedule | Payload attestations, ISO build, manifest, and QEMU boot |
| Installer installation | Weekly schedule and forced release candidate | Non-interactive Kickstart install, disk reboot, and installed-system readiness |
| Publication | Trusted main runs | Images, tags, signatures, provenance, SPDX software bills of materials, and caches |
| Release | Manual release dispatch | Exact source candidate and every promoted digest and attestation |

`CI gate` is the stable required check. Its result covers every image and
installer job selected for the change. The checked-in branch policy is
`automation/github/policies/main-protection.json`.

Pull requests and merge groups divide selected profiles among at most four
dependency-aware shards, co-locating shared lineages while balancing estimated
build and rechunk cost. Each shard verifies and loads the locked Bluefin digest
once, builds roots with `Containerfile`, and builds descendants with
`Containerfile.derived`. Ancestors needed only as local parents skip duplicate
rechunking; every selected profile remains a fully rechunked target in exactly
one shard. No mutable image state crosses a job boundary.

Events whose classification is predetermined (scheduled runs and publishing
workflow dispatches) use a shallow checkout. Diff-classified pull requests,
merge groups, pushes, and validation dispatches retain complete history. Merge
groups fail safe to all expensive validation when the supplied base is not an
ancestor of the synthetic head.

The Flake declares the public `purplefin.cachix.org` substituter and key. Every
Nix job uses the repository's pinned `setup-nix` action for GitHub access and
read-through Cachix configuration, with automatic store watching disabled.
`nix shell --accept-flake-config .#ci-check -c purplefin-ci-check` explicitly
builds only the declared checks in one parallel Nix invocation, then validates
every standard Flake output without additional builds. It resolves the checks'
reference-free proof outputs, rejects any closure larger than 1 MiB, and pushes
only those proofs. The `CACHIX_AUTH_TOKEN` repository secret enables writes on
protected events and same-repository pull requests. Fork pull requests use the
public cache for substitution.

Workflow secrets cross into jobs only through declared inputs on the pinned
`setup-nix` action. That action maps GitHub's secret values to the SecretSpec
`github-actions` profile, whose environment-backed provider masks and exports
the declared names through `GITHUB_ENV`. Later steps consume only the exported
`CACHIX_AUTH_TOKEN` and `MERGE_QUEUE_TOKEN` variables; workflow commands do not
read the GitHub secrets context directly.

## Image publication

Profiles build parent-first. Each published digest has:

- profile and channel tags;
- a keyless GitHub Actions Cosign signature;
- GitHub build provenance;
- an SPDX software bill of materials attestation;
- OCI labels for version, source, profile, build input, parent, and upstream
  digests.

Trusted builds first write only profile-specific candidate tags. Ordered base,
hardware, and role jobs sign those immutable digests and attach provenance;
tier-specific reusable jobs then attest their software bills of materials. A
single final promotion job verifies the complete selected graph—including
parent digests and every signer identity—before moving any public channel tag.
Normal publication and the release promotion phase share one non-cancelling
concurrency group. The release preparation phase remains outside that group so
it can wait for or dispatch the exact-source build without deadlocking it.
An interrupted run is therefore repairable: missing signatures or provenance
select a rebuild, while a missing software bill of materials attestation selects
only that attestation job. The signed attestation is also the release asset
source; Purplefin does not maintain a second unsigned software bill of materials
cache package. Pull requests and merge candidates validate candidates with
read-only registry access.

The manual obsolete-tag cleanup queries only the primary image package. Build
and installer caches live in isolated sibling packages and are intentionally
outside its deletion scope.

The fast installer contract is part of the ordinary Nix check graph. A full ISO
is selected only for the installer container/rootfs, its build or smoke
applications, the Image Builder lock, or the Nix toolchain lock. Shared Flake
exports, workflows, profile modules, and installer unit tests are validated by
the contract without rebuilding an unchanged ISO.

Full installer validation builds the live Anaconda environment from a pinned,
minimal Fedora bootc image. The signed Purplefin image is passed separately as
Image Builder's installer payload, so desktop and developer packages are not
duplicated into the live squashfs. The version-3 environment fingerprint covers
the Fedora base, installer context, and mutable profile tag, but not the
changing payload digest. Trusted `main` builds publish and keylessly sign that
environment; pull requests reuse it only after verifying the main
installer-workflow identity. Exact-source integrity remains independent: the
selected digest must pass signature, provenance, and SPDX checks before Image
Builder embeds it, while the installed bootc update origin tracks the profile
tag. The pinned Image Builder image is pulled in parallel with environment
preparation. OSBuild stage and RPM metadata caches are mounted explicitly. The pinned
builder's generic-ISO path otherwise leaves squashfs-tools at its Zstd
level-15 default. An audited, digest-locked stage drop-in selects Zstd level 1
for both ISO variants; the compatibility override is removed when Image
Builder exposes a supported compression-level control. The installer manifest
records the method, level, override checksum, and upstream stage checksum.
The QEMU smoke test exits as soon as `anaconda.service` emits the
Purplefin-owned readiness marker instead of waiting for its safety timeout.

Scheduled runs and forced release-candidate builds additionally serve a CI-only
Kickstart to the release ISO kernel. The guest must fetch it within three
minutes and finish installing to a disposable disk within twenty minutes. A
separate visible step reboots without the ISO and has three minutes to prove,
through bootc status v1, that the booted digest is the verified payload and the
update origin is the mutable profile tag. CI Kickstart state is never uploaded
as a user artifact; the published ISO remains interactive. The action summary
records cache version/input/hit, update origin, and separate build, smoke,
install, and installed-boot durations.

Syft scans the final mounted OCI filesystem because Purplefin images are
assembled from Bluefin and RPM content rather than from a Nix store closure.
The Flake pins Syft and wraps generation, normalization, size checks, and
attestation extraction. `sbomnix` is intentionally not used for this boundary:
it describes Nix derivation closures, which would omit the runtime RPM payload.

## Trusted updates

Dependabot updates pinned GitHub Actions. Scheduled workflows update
`flake.lock`, the digest-pinned Image Builder container, and the Bluefin stable
OCI lock through validated pull requests. Both OCI locks record an explicit
architecture and immutable manifest digest. The Bluefin updater additionally
verifies its committed Cosign issuer and identity. Nix-provided Skopeo streams
that exact digest directly into container storage without creating a container
archive in the Nix store. The daily build also checks independently managed
RPMs for updates against the committed Bluefin base.

GitHub keeps triggers, permissions, environments, matrices, pull request
creation, and attestations visible in workflow YAML. Operational planning,
validation, gating, and promotion are focused Nix packages invoked with
`nix shell`; no mutable runner profile or workflow-wide toolset is installed.
The remaining third-party Actions perform GitHub-native work such as checkout,
attestation, artifact transfer, and pull-request creation.

The same leaves are declared as a local devenv task graph. Run the complete
local graph with `nix shell --accept-flake-config .#devenv -c devenv tasks run ci:check`,
or isolate a leaf with `nix shell --accept-flake-config .#devenv -c devenv tasks
run --mode single --option 'packages:pkgs!' '' ci:prepare`. Hosted jobs invoke the
leaf packages directly because that avoids cold devenv startup while retaining
identical pinned commands and Cachix reuse.

Purplefin's package universe follows the rolling
`DeterminateSystems/nixpkgs-weekly/0` FlakeHub series. Home Manager follows that
same Nixpkgs input and is fetched from Determinate's public FlakeHub mirror at
`nix-community/home-manager/0`; lock validation rejects drift from either URL.

The weekly Determinate Nix updater resolves the latest stable upstream
release, pins both the installer asset and its SELinux policy by SHA-256, and
opens the same trusted-update pull-request path used by the OCI source locks.

When configured, the SecretSpec-mapped `MERGE_QUEUE_TOKEN` advances trusted
update pull requests through the merge queue with repository-scoped Contents
and Pull requests read/write access. `AUTOMATION_UPDATE_LOGIN` names that
token's pull request author; the GitHub Actions app identity is trusted by
default.

## Create a release

Dispatch `Release Purplefin` from `main` and select `auto`, `patch`, `minor`, or
`major`. The workflow:

1. selects the version and, when needed, merges its stable `VERSION` through a
   protected, CI-gated pull request;
2. builds or reuses an all-profile candidate from that exact merge commit;
3. verifies every signature, provenance statement, SPDX attestation, profile
   label, and source revision;
4. promotes the existing digests to versioned tags;
5. publishes the profile manifest, compressed SPDX documents, and release
   notes;
6. advances `VERSION` through a second protected, CI-gated pull request.

Stable changelog entries use `Added`, `Changed`, `Fixed`, and `Security`
sections.

Release-preparation pull requests may set `VERSION` and the dated changelog
entry in advance. After that commit reaches `main`, dispatch the release with a
`patch` bump (or `auto` when the conventional-commit history selects the same
version). If the stable version is already present, the workflow uses that
protected `main` commit directly instead of creating an empty version change.
