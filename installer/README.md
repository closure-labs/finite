# Purplefin Anaconda installer

The installer workflow builds OSBuild's supported `bootc-generic-iso` image
type with a digest-pinned `ghcr.io/osbuild/image-builder-cli` container.

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
The workflow uploads the ISO, SHA-256 checksum, provenance attestation, and QEMU
smoke-boot log. The weekly run uses `base-generic-x86_64`; manual runs can select
any tag listed by the workflow.
