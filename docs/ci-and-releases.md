# CI, publication, and releases

GitHub Actions selects work from the changed paths and the Nix-generated image
graph. The Flake supplies the check and build applications; workflows supply
events, permissions, runners, environments, attestations, and artifact upload.

## Validation layers

| Layer | Runs when | Validates |
| --- | --- | --- |
| Repository | Every pull request and main build | Flake checks, generated data, source, tests, and workflows |
| Candidate images | Image inputs change | Selected profiles and descendants using read-only registry access |
| Installer | Installer inputs change or on schedule | Payload attestations, ISO build, manifest, and QEMU boot |
| Publication | Trusted main runs | Images, tags, signatures, provenance, SPDX SBOMs, and caches |
| Release | Manual release dispatch | Exact source candidate and every promoted digest and attestation |

`CI gate` is the stable required check. Its result covers every image and
installer job selected for the change. The checked-in branch policy is
`automation/github/policies/main-protection.json`.

The Flake declares the public `purplefin.cachix.org` substituter and key. Every
Nix job uses the repository's pinned `setup-nix` action for GitHub access and
read-through Cachix configuration, with automatic store watching disabled.
`nix run .#ci` builds every declared check once, resolves its reference-free
proof outputs, rejects any closure larger than 1 MiB, and explicitly pushes only
those proofs. The `CACHIX_AUTH_TOKEN` repository secret enables writes on
protected events and same-repository pull requests. Fork pull requests use the
public cache for substitution.

## Image publication

Profiles build parent-first. Each published digest has:

- profile and channel tags;
- a keyless GitHub Actions Cosign signature;
- GitHub build provenance;
- an SPDX SBOM attestation;
- OCI labels for version, source, profile, build input, parent, and upstream
  digests.

Matching signed images and digest-bound SBOM cache artifacts are reused. Pull
requests and merge candidates validate candidates with read-only registry
access, while trusted `main` runs publish signed results.

## Trusted updates

Dependabot updates pinned GitHub Actions. Scheduled workflows update
`flake.lock`, the digest-pinned Image Builder container, and the Bluefin stable
OCI lock through validated pull requests. Both OCI locks record an explicit
architecture and immutable manifest digest. The Bluefin updater additionally
verifies its committed Cosign issuer and identity. Nix-provided Skopeo streams
that exact digest directly into container storage without creating a container
archive in the Nix store. The daily build also checks independently managed
RPMs for updates against the committed Bluefin base.

GitHub keeps triggers, permissions, environments, matrices, PR creation, and
attestations visible in workflow YAML. Each job otherwise installs one
domain-specific Flake toolset, so ORAS, Cosign, Skopeo, Syft, jq, and GitHub CLI
behavior comes from `flake.lock` rather than ad hoc setup actions.

When configured, `MERGE_QUEUE_TOKEN` advances trusted update pull requests
through the merge queue with repository-scoped Contents and Pull requests
read/write access. `AUTOMATION_UPDATE_LOGIN` names that token's pull request
author; the GitHub Actions app identity is trusted by default.

## Create a release

Dispatch `Release Purplefin` from `main` and select `auto`, `patch`, `minor`, or
`major`. The workflow:

1. selects the version and merges its stable `VERSION` through a protected,
   CI-gated pull request;
2. builds or reuses an all-profile candidate from that exact merge commit;
3. verifies every signature, provenance statement, SPDX attestation, profile
   label, and source revision;
4. promotes the existing digests to versioned tags;
5. publishes the profile manifest, compressed SPDX documents, and release
   notes;
6. advances `VERSION` through a second protected, CI-gated pull request.

Stable changelog entries use `Added`, `Changed`, `Fixed`, and `Security`
sections.
