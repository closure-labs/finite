# Builds and releases

## Selective image builds

Nix computes a semantic build-input hash and exact module delta for every
profile. A base change selects every descendant, a hardware change selects its
hardware branch, and a role change selects its profile. The planner also
selects descendants whose published parent digest has advanced.

GitHub-hosted runners build the graph parent-first. Root and hardware images
become immutable parents for their derived profiles. Buildah stores reusable
layers in `purplefin-build-cache`, and completed SPDX documents are stored as
digest-bound OCI artifacts in `purplefin-sbom-cache`.

Pull requests and merge candidates build the selected graph with read-only
package access. Pushes to `main`, scheduled runs, and explicit `main` workflow
dispatches publish images and refresh caches.

## Published artifacts

Each published profile receives:

- immutable image content derived from verified parent digests;
- channel and profile tags that alias one published digest;
- a keyless GitHub Actions Cosign signature;
- GitHub build provenance;
- an SPDX SBOM attestation generated from the merged image filesystem;
- OCI labels containing the version, source revision, profile, build input,
  parent digest, and upstream digest.

The [CI objectives](ci-objectives.md) describe the validation layers that guard
these artifacts.

## Version selection and release promotion

`VERSION` is embedded in the OCI label and `/usr/share/purplefin/version`.
The release workflow selects SemVer from conventional commits, with manual
patch, minor, and major choices for release planning.

A release run prepares the stable version, obtains a successful all-profile
candidate build from the exact source commit, and verifies every published
signature, provenance statement, SPDX attestation, profile label, and source
revision. Release-environment approval then promotes the existing digests to
`PROFILE-vVERSION` tags.

The GitHub release contains the immutable profile-to-digest mapping, build
manifest, and compressed SPDX document for every profile. CI publishes the
release and advances `VERSION` to the next patch development version after all
image tags and release assets are complete.

Dispatch `Release Purplefin` from `main` and choose `auto`, `patch`, `minor`, or
`major`. The `auto` choice maps breaking changes to major, features to minor,
and the remaining conventional commits to patch.
