# Purplefin Anaconda installer

The installer workflow builds OSBuild's supported `bootc-generic-iso` image
type with a digest-pinned `ghcr.io/osbuild/image-builder-cli` container.
This intentionally uses the unified Image Builder CLI directly. The official
`osbuild/bootc-image-builder-action` wraps the deprecated standalone
`bootc-image-builder` interface and defaults to its mutable `latest` container,
so adopting it would move the installer away from OSBuild's current migration
target. `osbuild/release-action` automates OSBuild's own upstream release notes,
version bump, GitHub release, and Slack announcement; it is not a builder tool
version manifest or an SBOM action.

At dispatch time a maintainer selects one published Purplefin profile. The
workflow resolves that tag, verifies its keyless GitHub Actions Cosign
signature, and passes the resulting immutable digest both to the installer
environment and as the embedded Anaconda payload. Package composition never
happens during installation.

Each profile also has a Nix-generated Blueprint in `config/profiles`. Those
files are intended for OSBuild disk-image types that accept bootc Blueprint
filesystem/user customization. The generic installer ISO consumes the
immutable bootc payload directly; RPM composition remains part of the bootc
image rather than the Blueprint.

`Containerfile` implements the generic ISO contract: Anaconda and ISO tooling,
kernel and initramfs, EFI files, `/usr/lib/image-builder/bootc/iso.yaml`, and an
interactive-defaults kickstart containing the immutable payload reference.
The workflow verifies the payload's build provenance and SPDX attestation,
records the payload, Image Builder, installer-environment, source, and ISO
digests in `installer-manifest.json`, and attests that manifest with the ISO and
checksums. Published runs upload those artifacts and the QEMU smoke-boot log.
Every run uploads a compact diagnostic bundle and writes phase outcomes,
durations, cache state, and resolved digests to the Actions summary. The weekly
run uses `base-generic-x86_64`; manual runs can select any tag listed by the
workflow.

The installer consumes an already published, signed Purplefin OCI digest. The
profile workflow's Syft SPDX document, digest-keyed SBOM cache, and GitHub SBOM
attestation remain bound to that embedded OCI digest, and the installer
component manifest records the attestation identity needed to verify it.

The workflow and `Build Purplefin` share one repository-local installer build
action. A change classifier selects it for installer workflow, action, overlay,
QEMU smoke-test, and installer-toolchain changes, and `CI gate` requires the
selected result for pull requests and merge candidates. Candidate builds use
read-only package access. Weekly and explicit main runs can update matching
layers in the shared GHCR build cache; the cache key follows the immutable
payload digest, build arguments, Containerfile, and overlay content.

Following OSBuild's own pinned-CI-image update pattern, a weekly workflow
resolves `ghcr.io/osbuild/image-builder-cli:latest` only as a discovery input
and writes its immutable manifest digest into the installer workflow. A change
is proposed as a single-file pull request. The updater runs the normal CI gate
and builds and smoke-boots the generic installer from the candidate branch
before enabling auto-merge. This provides timely builder updates without using
a mutable image to construct an artifact.
