# CI, publication, and releases

GitHub Actions selects work from the changed paths and the Nix-generated image
graph. The Flake supplies the check and build applications; workflows supply
events, permissions, runners, environments, attestations, and artifact upload.
Path classification treats renames as a deletion plus an addition, so moving a
build input into a documentation directory cannot hide its original impact.
Installer validation is selected only by the installer graph, live overlay,
or pinned installer inputs; image-only aspects and repository tests do
not rebuild the unchanged ISO.

Classification and planning cross the workflow boundary as one schema-versioned,
strictly validated JSON plan. `finite-ci-prepare` is the only workflow-facing
authority: it records whether the diff is trustworthy and the exact image,
software-bill-of-materials, promotion, and installer jobs required for the run.
Profile selection uses the generated
per-profile build-input fingerprints. The four current image profiles pair each
foundation with each hardware target and build independently. Publication
additionally checks registry state, signatures,
provenance, RPM updates, and repair work before finalizing that lifecycle.

## Validation layers

| Layer | Runs when | Validates |
| --- | --- | --- |
| Repository | Every pull request and main build | Flake checks, generated data, source, tests, and workflows |
| Candidate images | Image inputs change | Selected profiles and descendants in four read-only, runner-local shards |
| Installer contract | Every pull request and main build | Pinned Project Bluefin inputs, live overlay, seed boundary, and smoke-test behavior |
| Installer image | Installer inputs change, a base payload is published, or on schedule | Payload attestations, ISO build, manifest, and QEMU boot |
| Installer installation | Installer-changing pull requests and merge groups, weekly schedule, and forced release candidate | Unattended bootc installation, three-partition GPT validation, clean-firmware UEFI boot, and installed-system identity |
| Publication | Trusted main runs | Images, tags, signatures, provenance, SPDX software bills of materials, and caches |
| Release | Manual release dispatch | Exact source candidate and every promoted digest and attestation |

`CI gate` is the stable required check. Its result covers every image and
installer job selected for the change. The checked-in branch policy is
`automation/github/policies/main-merge-queue.json`.

Pull requests and merge groups divide selected profiles among at most four
dependency-aware shards while balancing estimated build and rechunk cost. Each
shard verifies and loads the appropriate locked Bluefin digest, builds its
foundation-and-hardware profile with `Containerfile`, and fully rechunks every
selected target. No mutable image state crosses a job boundary.

Installer candidates use only the current repository's GHCR payload. Signature
and attestation verification follows the payload's audited OCI source label;
there is no alternate registry namespace or compatibility fallback.

Publication and pull-request validation share the focused
`finite-rechunk-image` Nix application. It preserves non-generated OCI
labels, format version 2, and the 127-layer ceiling, then validates the output
digest and labels. On publication, the workflow resolves the current profile
tag to an immutable digest and accepts it only when Finite's trusted
`build-profile.yml` identity signed it. When the source image's rpm-ostree
advertises `--previous-build`, that verified `docker://...@sha256:...` reference
enables incremental rechunking without downloading the previous image. Missing,
unverifiable, unsupported, or failed incremental inputs fall back to the same
full rechunk used by validation.

Each profile summary records upstream-load, container-build, and rechunk
durations, incremental/full mode, and the previous-build digest. The rollout
comparison uses the v0.3.0 baseline and, in particular, Bluefin DX Dell's
547-second rechunk. After the next three comparable base builds, incremental
mode remains enabled only if its median is at least 15% faster (465 seconds or
less for that baseline). Otherwise only the workflow's previous-build input is
removed; the centralized application, validation, and timing remain.

Events whose classification is predetermined (scheduled runs and publishing
workflow dispatches) use a shallow checkout. Repository checks are also
shallow because their result is independent of Git history. Diff-classified
pull requests, merge groups, pushes, and validation dispatches retain complete
history. Merge groups fail safe to all expensive validation when the supplied
base is not an ancestor of the synthetic head.

The Flake is the single source of truth for the Finite Cachix
substituter and key. Every Nix job uses the repository's pinned `setup-nix`
action for GitHub access and read-through cache configuration, with automatic
store watching disabled.
`nix shell --accept-flake-config .#ci-check -c finite-ci-check` explicitly
builds only the declared checks in one bounded Nix invocation, then validates
every standard Flake output without additional builds. The shared setup caps
Nix at four simultaneous jobs and one core per derivation on GitHub-hosted
runners. It resolves the checks'
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

Trusted builds first write only profile-specific candidate tags. The
foundation-and-hardware jobs sign those immutable digests and attach provenance;
reusable jobs then attest their software bills of materials. A
single final promotion job verifies the complete selected graph—including
parent digests and every signer identity—before moving any public channel tag.
Normal publication and the release promotion phase share one non-cancelling
concurrency group. The release preparation phase remains outside that group so
it can wait for or dispatch the exact-source build without deadlocking it.
An interrupted run is therefore repairable: missing signatures or provenance
select a rebuild, while a missing software bill of materials attestation selects
only that attestation job. The signed attestation is also the release asset
source; Finite does not maintain a second unsigned software bill of materials
cache package. Pull requests and merge candidates validate candidates with
read-only registry access.

The manual obsolete-tag cleanup queries only the primary image package. Build
and installer caches live in isolated sibling packages and are intentionally
outside its deletion scope.

The fast installer contract is part of the ordinary Nix check graph. A full ISO
is selected only when the pinned Project Bluefin ISO source, installer bundle,
Finite live overlay, installer applications, or Nix toolchain changes.

Full validation follows Project Bluefin's `dakota-iso` architecture and embeds
the pinned `bootc-installer` Flatpak. It verifies both the selected Finite
payload and the digest-pinned Dakota live root. A reusable seed is selected by
the Dakota live digest, pinned ISO source revision, installer checksum, Debian
builder digest, Finite overlay and logo, and seed-builder digest. The seed is
the completed payload-independent LZ4 SquashFS, boot tar, and preflight proof—not a large
Podman store. Trusted `main` and scheduled builds publish and keylessly sign
those files as an OCI artifact in the sibling GHCR package; pull requests reuse
only artifacts signed by either trusted installer-producing workflow. An exact
GitHub Actions cache populated only by trusted `main` accelerates all exact
matches. Pull requests and merge groups may restore that key but cannot save a
branch-scoped copy; a miss falls back to the signed, checksum-validated GHCR
seed. The selected Finite digest and update tag are a small JSON file on the
ISO, applied to the writable live overlay by a pre-installer service. Dakota
therefore assembles the systemd-boot network ISO without rebuilding the live
image, recompressing its SquashFS, or embedding the Finite payload.

## Repository security policy

`automation/github/repository-security.json` is the reviewable source of truth
for Actions allowlisting and SHA pinning, default token permissions, security
features, and the protected `release` and `package-cleanup` environments. Both
environments allow the solo maintainer to approve their own run, require
`declarative-dale`, accept deployments only from `main`, and deny administrator
bypass.

Audit the live read-only settings without placing mutation credentials in CI:

```console
nix run .#repository-security-audit
```

The command writes one strict JSON result to standard output and diagnostics to
standard error. Vulnerability alerts, Dependabot security updates, secret
scanning, and push protection remain enabled alongside Finite's Nix and OCI
updaters because GitHub's dependency graph does not cover those lock formats.

The smoke phase waits for the Finite-owned live-session readiness marker. Before
Fisherman can touch the target disk, preflight validates its recipe, required
executables, exact network reference, registry resolution, and disk-backed
scratch capacity. The end-to-end phase supplies the checked-in unattended JSON
recipe, installs onto a 64 GiB disposable disk, validates Project Bluefin's
three-partition GPT layout, and boots with a fresh OVMF variable store. The
installed system must report Fedora 44, hostname `finite`, a Btrfs root, a
working GRUB2 configuration, the verified signed source digest, the exact
OSTree deployment checksum recorded during installation, and the expected
mutable update reference. The bootc manifest digest is recorded separately
because Fisherman's registry-to-OCI-layout copy may change manifest bytes.
The action summary records seed identity/hit/publication state plus separate
seed, ISO, smoke, install, and installed-boot durations.

Syft scans the final mounted OCI filesystem because Finite images are
assembled from Bluefin and RPM content rather than from a Nix store closure.
The Flake pins Syft and wraps generation, normalization, size checks, and
attestation extraction. `sbomnix` is intentionally not used for this boundary:
it describes Nix derivation closures, which would omit the runtime RPM payload.

## Trusted updates

Dependabot updates pinned GitHub Actions. Scheduled workflows update
`flake.lock`, Determinate Nix, Home Manager, and the Bluefin stable OCI locks
through validated pull requests. Bluefin and Bluefin DX are checked twice
daily at 07:07 and 19:07 UTC. Every OCI lock records an explicit architecture
and immutable manifest digest. The
Bluefin updater additionally verifies its committed Cosign issuer and
identity. Nix-provided Skopeo streams that exact digest directly into container
storage without creating a container archive in the Nix store. The daily build
also checks independently managed RPMs for updates against the committed
Bluefin base.

GitHub keeps triggers, permissions, environments, matrices, pull request
creation, and attestations visible in workflow YAML. Operational planning,
validation, gating, and promotion are focused Nix packages invoked with
`nix shell`; no mutable runner profile or workflow-wide toolset is installed.
`finite-profile-stage` owns immutable profile staging, `finite-image-verify`
provides the shared label/signature/provenance/SBOM verifier, and
`finite-release-control` owns the release state machine. These applications
emit schema-versioned strict JSON on standard output and diagnostics on standard
error. `finite-github-output` is the only adapter from validated scalar report
fields to `GITHUB_OUTPUT`. Their package definitions are split by domain under
`lib/ci-applications` and assembled with a scoped `callPackageWith` interface.
The remaining third-party Actions perform GitHub-native work such as checkout,
attestation, artifact transfer, and pull-request creation.

The same leaves are declared as a local devenv task graph. Run the complete
local graph with `nix shell --accept-flake-config .#devenv -c devenv tasks run ci:check`,
or isolate a leaf with `nix shell --accept-flake-config .#devenv -c devenv tasks
run --mode single --option 'packages:pkgs!' '' ci:prepare`. Hosted jobs invoke the
leaf packages directly because that avoids cold devenv startup while retaining
identical pinned commands and Cachix reuse.

Finite's package universe follows the stable, seven-day-cooled
`DeterminateSystems/nixpkgs-26.05-chilled/0.1` FlakeHub series. Home Manager is
constrained to the matching 26.05 series at `nix-community/home-manager/0.2605`
and follows that same Nixpkgs input; lock validation rejects drift from either
URL.

A separate weekly release-series job checks the official Nixpkgs
`nixos-YY.MM` and Home Manager `release-YY.MM` branches. It advances the paired
series only after both upstream branches and both corresponding FlakeHub mirrors
are available. The ordinary weekly lock refresh then remains within that
selected stable series.

Fast-moving applications and tools, currently Bitwarden Desktop and SecretSpec,
may be selected from the cooled weekly package input when the stable package is
insecure or lacks required commands. This does not change the stable Nixpkgs
instance used to evaluate Home Manager.

The weekly Determinate Nix updater resolves the latest stable upstream
release, pins both the installer asset and its SELinux policy by SHA-256, and
opens the same trusted-update pull-request path used by the OCI source locks.

The SecretSpec-mapped `MERGE_QUEUE_TOKEN` advances trusted update pull requests
through the merge queue. Scope a fine-grained token to the Finite repository
with Actions, Contents, and Pull requests read/write access;
`AUTOMATION_UPDATE_LOGIN` names that token's pull request author. Merge-queue
workflows fail during setup when the credential is unavailable instead of
falling back to the workflow's built-in token.

Releases require that credential before either job can publish or modify a
version. Both protected `VERSION` handoffs use it because pull requests queued
with the workflow's built-in `GITHUB_TOKEN` cannot emit the `merge_group` event
needed to start required validation. Each handoff may wait for up to 120 minutes,
matching the repository merge queue's response timeout.

## Create a release

Dispatch `Release Finite` from `main` and select `auto`, `patch`, `minor`, or
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
entry in advance. After that commit reaches `main`, dispatch the release with
`auto`. When `VERSION` already contains a stable version, the workflow treats it
as staged, verifies that it is newer than the latest tag, and ignores the bump
selector. It then uses that protected `main` commit directly instead of creating
an empty version change.
