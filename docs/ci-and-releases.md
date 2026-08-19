# CI, publication, and releases

GitHub Actions selects work from the changed paths and the Nix-generated image
graph. The Flake supplies the check and build applications; workflows supply
events, permissions, runners, environments, attestations, and artifact upload.
Path classification treats renames as a deletion plus an addition, so moving a
build input into a documentation directory cannot hide its original impact.
Installer validation is selected only by the installer graph, generated profile
blueprints, or their pinned tools; image-only aspects and repository tests do
not rebuild the unchanged ISO.

Classification and planning cross the workflow boundary as schema-versioned
JSON contracts. Classification records whether its diff is trustworthy and
which validation domains are eligible. The lifecycle contract then records the
exact image targets and the build, software-bill-of-materials, promotion, and
installer jobs required for the run. Profile selection uses the generated
per-profile build-input fingerprints and parent graph: changed targets expand to
their descendants, while shard planning adds ancestors only as local build
dependencies. Publication additionally checks registry state, signatures,
provenance, RPM updates, and repair work before finalizing that lifecycle.

## Validation layers

| Layer | Runs when | Validates |
| --- | --- | --- |
| Repository | Every pull request and main build | Flake checks, generated data, source, tests, and workflows |
| Candidate images | Image inputs change | Selected profiles and descendants in four read-only, runner-local shards |
| Installer | Installer inputs change or on schedule | Payload attestations, ISO build, manifest, and QEMU boot |
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
`nix run .#ci` builds every declared check once, resolves its reference-free
proof outputs, rejects any closure larger than 1 MiB, and explicitly pushes only
those proofs. The `CACHIX_AUTH_TOKEN` repository secret enables writes on
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
validation, gating, and promotion are Nix-defined applications. Each job builds
one domain-specific Flake toolset into a fixed runner-local link and adds only
that toolset to `PATH`, so ORAS, Cosign, Skopeo, Syft, jq, and GitHub CLI behavior
comes from `flake.lock` without mutating a persistent Nix profile.

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
