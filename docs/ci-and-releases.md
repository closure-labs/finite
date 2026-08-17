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

## Image publication

Profiles build parent-first. Each published digest has:

- profile and channel tags;
- a keyless GitHub Actions Cosign signature;
- GitHub build provenance;
- an SPDX SBOM attestation;
- OCI labels for version, source, profile, build input, parent, and upstream
  digests.

Matching signed images and digest-bound SBOM cache artifacts are reused. Pull
requests and merge candidates cannot publish.

## Trusted updates

Dependabot updates pinned GitHub Actions. Scheduled workflows update
`flake.lock` and the digest-pinned Image Builder container through validated
pull requests. `MERGE_QUEUE_TOKEN` is optional; when set, it must be scoped to
this repository with Contents and Pull requests read/write access.

## Create a release

Dispatch `Release Purplefin` from `main` and select `auto`, `patch`, `minor`, or
`major`. The workflow:

1. selects the version and validates its changelog entry;
2. builds or reuses an all-profile candidate from the exact source commit;
3. verifies every signature, provenance statement, SPDX attestation, profile
   label, and source revision;
4. promotes the existing digests to versioned tags;
5. publishes the profile manifest, compressed SPDX documents, and release
   notes;
6. advances `VERSION` to the next patch development version.

Stable changelog entries use `Added`, `Changed`, `Fixed`, and `Security`
sections.
