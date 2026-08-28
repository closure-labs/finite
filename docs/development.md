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
nix shell --accept-flake-config .#ci-check -c finite-ci-check
```

The CI application explicitly builds only the declared checks in one bounded
Nix invocation, then runs the canonical `nix flake check --no-build` and
verifies that every check produces a reference-free proof closure below 1 MiB.
The shared GitHub setup limits Nix to four simultaneous jobs and one core per
derivation so runner CPU and memory usage remain predictable.
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
nix run .#local-cache -- --max-jobs 2 --cores 2
```

On a 16 GiB or thermally constrained workstation, use `--max-jobs 1` while
keeping `--cores 2`; already-realized checks are reused on the next run. The
wrapper resolves the aggregate check derivation in a short-lived Nix process
before starting builders so the large Flake evaluator heap is not retained for
the duration of the build.

The `local-cache` app uses SecretSpec profile `local-cache` and scope `cachix`.
SecretSpec resolves the workstation value from
`$HOME/.other-fun-things/.cachix-auth-finite`, then the app publishes the
evaluated closure-guarded proof outputs.

GitHub-hosted jobs use the separate SecretSpec `github-actions` profile. The
repository's setup action binds explicitly supplied GitHub Action secrets to
that environment-backed provider and exports only the declared
`CACHIX_AUTH_TOKEN` and `MERGE_QUEUE_TOKEN` names for later steps.

## Build a local image

The image application resolves immutable inputs, generates the build contract,
and invokes Podman:

```bash
nix shell --accept-flake-config .#ci-image-build -c finite-image-build \
  bluefin-generic localhost/finite:bluefin-generic
nix shell --accept-flake-config .#ci-image-build -c finite-image-build \
  bluefin-dx-next localhost/finite:dev-next
```

Profile names and their stable ordering are declared in
`lib/domain-catalog.nix`; `modules/profiles/definitions.nix` maps that pure data
onto Den aspects.

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
- `bootc/generated/kernel-next/` with the hash-locked Fedora 7.2 RPM set

Build consumers receive this store path directly. To make a writable copy for
inspection, copy the desired files from the `result` symlink.

## Brand assets

The canonical transparent mark is
`modules/aspects/base/rootfs/usr/share/finite/finite-logo.png`. The same source
is used for shared image branding and the rEFInd Linux/Finite icons. Plymouth
and GDM require fixed-size transparent canvases, so their checked-in derivatives
are centered at 149×43 and 150×61 respectively.

When the canonical artwork changes, regenerate those derivatives with
ImageMagick and keep both Plymouth filenames identical:

```console
magick finite-logo.png -resize 37x35 -gravity center -background none \
  -extent 149x43 watermark.png
magick finite-logo.png -resize 51x49 -gravity center -background none \
  -extent 150x61 fedora-gdm-logo.png
```

The aspect contracts verify the canonical and rEFInd copies and ensure both
Plymouth watermark names remain identical.

## Useful outputs

| Command | Result |
| --- | --- |
| `nix build .#architecture` | Mermaid rendering of the evaluated Den graph |
| `nix shell .#ci-source-verify -c finite-source-verify bluefin` | Verify the locked digest and Cosign identity |
| `nix shell .#ci-source-verify -c finite-source-verify bluefin-dx` | Verify the locked Bluefin DX digest and Cosign identity |
| `nix shell .#ci-source-verify -c finite-source-verify determinate-nix` | Verify the pinned Determinate installer and SELinux policy hashes |
| `nix shell .#ci-load-bluefin -c finite-load-bluefin bluefin` | Copy the verified digest into container storage |
| `nix shell .#ci-source-update -c finite-source-update bluefin` | Refresh and verify the Bluefin lock |
| `nix shell .#ci-source-update -c finite-source-update bluefin-dx` | Refresh and verify the Bluefin DX lock |
| `nix shell .#ci-source-update -c finite-source-update determinate-nix` | Refresh the stable Determinate Nix release lock |
| `nix run .#home-profile -- --help` | Generate a standalone Home Manager profile |
| `nix run .#home-init -- --help` | Validate, stage, build, and install the self-contained Home Manager flake |
| `nix flake new -t .#home-manager PATH` | Create the canonical standalone Home Manager template |
| `nix flake new -t .#home-bluefin PATH` | Compatibility alias; bootstrap writes the selected profile variables |
| `nix flake new -t .#home-bluefin-dx PATH` | Compatibility alias; bootstrap writes the selected profile variables |
| `nix run .#cloud-init -- ...` | Generate a NoCloud Home Manager seed |
| `nix build .#syft` | Pinned Syft package |
| `nix shell .#ci-image-sbom -c finite-image-sbom validate <file>` | Validate a normalized SPDX image software bill of materials |
| `nix shell .#ci-rechunk-image -c finite-rechunk-image --source <image> --output <transport>` | Rechunk a local bootc image with the shared format-v2 policy |
| `nix shell .#ci-installer-smoke -c finite-installer-smoke <iso>` | QEMU installer boot test |
| `nix shell .#ci-installer-e2e -c finite-installer-e2e install <iso> <state> <source-digest>` | Install the signed source into a disposable disk |
| `nix shell .#ci-installer-e2e -c finite-installer-e2e boot <state> <reference>` | Boot and validate the installed disposable disk and exact OSTree deployment |
| `nix shell .#ci-release-notes -c finite-release-notes <version> CHANGELOG.md` | Release notes for one version |

## Repository layout

```text
modules/aspects/      co-located base, capability, hardware, and role features
modules/profiles/     typed catalogs, composition definitions, and bootc class
modules/repository/   checks, delivery, and GitHub operation graph
modules/sources/      typed source-lock module
sources/              auditable Bluefin, installer-source, and tool locks
bootc/builder/        container build entrypoints and shared shell libraries
lib/                  Flake-owned applications, checks, and artifact rendering
installer/            Project Bluefin live overlay and source-preparation script
automation/           declarative GitHub repository policies
tests/                focused repository and build contracts
```

See [Troubleshooting](troubleshooting.md) for failed checks and local build
diagnostics.
