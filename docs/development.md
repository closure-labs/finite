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
nix run .#ci
```

The CI application runs the canonical `nix flake check` and verifies that every
check produces a reference-free proof closure below 1 MiB. Authorized
workstations and trusted GitHub events publish those proofs to Cachix.

On the primary workstation, run the check graph with Cachix upload enabled:

```bash
nix run .#local-cache
```

The `local-cache` app uses SecretSpec profile `local-cache` and scope `cachix`.
It accepts `CACHIX_AUTH_TOKEN` from the environment or loads the workstation
value from `$HOME/.other-fun-things/.cachix-purplefin-auth`, then publishes the
evaluated closure-guarded proof outputs.

## Build a local image

The image application resolves immutable inputs, generates the build contract,
and invokes Podman:

```bash
nix run .#image-build -- base-generic localhost/purplefin:base-generic
nix run .#image-build -- dale localhost/purplefin:dale
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
- `bootc/generated/upstream.json`
- `installer/config/profiles/*.toml`

Build consumers receive this store path directly. To make a writable copy for
inspection, copy the desired files from the `result` symlink.

## Useful outputs

| Command | Result |
| --- | --- |
| `nix build .#architecture` | Mermaid rendering of the evaluated Den graph |
| `nix run .#source-verify -- bluefin` | Verify the locked digest and Cosign identity |
| `nix run .#source-verify -- image-builder` | Verify the locked installer builder digest |
| `nix run .#load-bluefin` | Copy the verified digest into container storage |
| `nix run .#source-update -- bluefin` | Refresh and verify the Bluefin lock |
| `nix build .#home-dale` | Home Manager activation package for `dale` |
| `nix build .#syft` | Pinned Syft package |
| `nix build .#sbomnix` | Pinned sbomnix package |
| `nix run .#installer-smoke -- <iso>` | QEMU installer boot test |
| `nix run .#release-notes -- <version> CHANGELOG.md` | Release notes for one version |

## Repository layout

```text
modules/aspects/      co-located base, capability, hardware, and role features
modules/profiles/     profile schema, composition, routing, and bootc class
modules/repository/   checks, delivery, and GitHub operation graph
modules/sources/      typed source-lock module
sources/              auditable OCI locks for Bluefin and Image Builder
bootc/builder/        full, derived, planning, and reuse engines
lib/                  Flake checks, applications, and artifact rendering
installer/            installer container and root filesystem
automation/           GitHub policy and release helpers
tests/                focused repository and build contracts
```

See [Troubleshooting](troubleshooting.md) for failed checks and local build
diagnostics.
