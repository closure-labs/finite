# Build and develop with Nix

The Nix Flake pins the development toolchain and exposes the repository's
checks, generated data, packages, and applications.

## Open the development environment

```bash
nix develop
```

Format and validate all source, generated data, profiles, Home Manager
configurations, workflows, and tests:

```bash
nix fmt
nix shell --accept-flake-config .#ci-check -c purplefin-ci-check
```

The CI application explicitly builds only the declared checks in one parallel
invocation, then runs the canonical `nix flake check --no-build` and verifies
that every check produces a reference-free proof closure below 1 MiB.
Authorized workstations and trusted GitHub events publish those proofs to
Cachix.

Pull requests and merge groups validate image profiles in up to four balanced
runner-local shards. Each foundation carries its locked Bluefin or Bluefin DX
upstream, and the shard loads the appropriate signed digest before building
and rechunking it with `--pull=never`. GitHub jobs do not share container
storage. Publishing remains an immutable-digest graph with independent signing
and attestations.

The Nix wrapper supplies the pinned orchestration tools. On GitHub-hosted
runners it deliberately delegates rootless container execution to the runner's
Buildah and Podman, retaining their user-namespace integration while Skopeo
loads the verified digest into the same storage.

On the primary workstation, run the check graph with Cachix upload enabled:

```bash
nix run .#local-cache
```

The `local-cache` app uses SecretSpec profile `local-cache` and scope `cachix`.
It accepts `CACHIX_AUTH_TOKEN` from the environment or loads the workstation
value from `$HOME/.other-fun-things/.cachix-purplefin-auth`, then publishes the
evaluated closure-guarded proof outputs.

GitHub-hosted jobs use the separate SecretSpec `github-actions` profile. The
repository's setup action binds explicitly supplied GitHub Action secrets to
that environment-backed provider and exports only the declared
`CACHIX_AUTH_TOKEN` and `MERGE_QUEUE_TOKEN` names for later steps.

## Build a local image

The image application resolves immutable inputs, generates the build contract,
and invokes Podman:

```bash
nix shell --accept-flake-config .#ci-image-build -c purplefin-image-build \
  bluefin-generic localhost/purplefin:bluefin-generic
nix shell --accept-flake-config .#ci-image-build -c purplefin-image-build \
  bluefin-dx-dell-xps-9350-intel localhost/purplefin:dale
```

Profile names are declared in `modules/profiles/definitions.nix`.

## Generated outputs

```bash
nix build .#generated
find -L result -type f -print
```

The output contains:

- `bootc/generated/image-matrix.json`
- `bootc/generated/profile-catalog.json`
- `bootc/generated/upstreams.json`
- `bootc/generated/home-profile-catalog.json`
- `installer/config/profiles/*.toml`

Build consumers receive this store path directly. To make a writable copy for
inspection, copy the desired files from the `result` symlink.

## Useful outputs

| Command | Result |
| --- | --- |
| `nix build .#architecture` | Mermaid rendering of the evaluated Den graph |
| `nix shell .#ci-source-verify -c purplefin-source-verify bluefin` | Verify the locked digest and Cosign identity |
| `nix shell .#ci-source-verify -c purplefin-source-verify bluefin-dx` | Verify the locked Bluefin DX digest and Cosign identity |
| `nix shell .#ci-source-verify -c purplefin-source-verify image-builder` | Verify the locked installer builder digest |
| `nix shell .#ci-source-verify -c purplefin-source-verify fedora-bootc` | Verify the locked minimal installer live-environment digest |
| `nix shell .#ci-source-verify -c purplefin-source-verify determinate-nix` | Verify the pinned Determinate installer and SELinux policy hashes |
| `nix shell .#ci-load-bluefin -c purplefin-load-bluefin bluefin` | Copy the verified digest into container storage |
| `nix shell .#ci-source-update -c purplefin-source-update bluefin` | Refresh and verify the Bluefin lock |
| `nix shell .#ci-source-update -c purplefin-source-update bluefin-dx` | Refresh and verify the Bluefin DX lock |
| `nix shell .#ci-source-update -c purplefin-source-update determinate-nix` | Refresh the stable Determinate Nix release lock |
| `nix build .#home-dale` | Home Manager activation package for `dale` |
| `nix build .#home-elad` | All-role Home Manager activation package without the Dell camera layer |
| `nix run .#cloud-init -- ...` | Generate a NoCloud Home Manager seed |
| `nix build .#syft` | Pinned Syft package |
| `nix shell .#ci-image-sbom -c purplefin-image-sbom validate <file>` | Validate a normalized SPDX image software bill of materials |
| `nix shell .#ci-installer-smoke -c purplefin-installer-smoke <iso>` | QEMU installer boot test |
| `nix shell .#ci-installer-e2e -c purplefin-installer-e2e <test-iso>` | Install a CI Kickstart ISO and boot its disposable disk |
| `nix shell .#ci-release-notes -c purplefin-release-notes <version> CHANGELOG.md` | Release notes for one version |

## Repository layout

```text
modules/aspects/      co-located base, capability, hardware, and role features
modules/profiles/     profile schema, composition, routing, and bootc class
modules/repository/   checks, delivery, and GitHub operation graph
modules/sources/      typed source-lock module
sources/              auditable OCI locks for Bluefin, Bluefin DX, and Image Builder
bootc/builder/        container build entrypoints and shared shell libraries
lib/                  Flake-owned applications, checks, and artifact rendering
installer/            installer container and root filesystem
automation/           declarative GitHub repository policies
tests/                focused repository and build contracts
```

See [Troubleshooting](troubleshooting.md) for failed checks and local build
diagnostics.
