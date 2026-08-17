# Development and local builds

The Nix Flake pins the development toolchain and exposes the repository's
checks, generated data, packages, and applications.

## Development shell

```bash
nix develop
```

Format and validate all source, generated data, profiles, Home Manager
configurations, workflows, and tests:

```bash
nix fmt
nix flake check --print-build-logs
```

`nix run .#ci` runs the same check graph.

On the primary workstation, run the check graph with Cachix upload enabled:

```bash
nix run .#local-cache
```

The `local-cache` app uses SecretSpec profile `local-cache` and scope `cachix`.
It accepts `CACHIX_AUTH_TOKEN` from the environment or loads the workstation
value from `$HOME/.other-fun-things/.cachix-purplefin-auth`. The default builds and pushes
only the small repository contract-check outputs to `purplefin`; it does not watch
the Nix store or upload the Bluefin archive and Home Manager closures. To cache
another explicitly selected small output, pass its installable after `--`:

```bash
nix run .#local-cache -- .#checks.x86_64-linux.upstream
```

## Build an image

The image application resolves immutable inputs, generates the build contract,
and invokes Podman:

```bash
nix run .#image-build -- base-generic localhost/purplefin:base-generic
nix run .#image-build -- dale localhost/purplefin:dale
```

Profile names are declared in `modules/profiles.nix`.

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

Materialize these files for tools that require repository-relative paths:

```bash
nix run .#export-artifacts
nix run .#export-artifacts -- .
```

## Useful outputs

| Command | Result |
| --- | --- |
| `nix build .#architecture` | Mermaid rendering of the evaluated Den graph |
| `nix build .#bluefin-upstream` | `npins`-locked Bluefin OCI archive |
| `nix build .#home-dale` | Home Manager activation package for `dale` |
| `nix build .#syft` | Pinned Syft package |
| `nix build .#sbomnix` | Pinned sbomnix package |
| `nix run .#installer-smoke -- <iso>` | QEMU installer boot test |
| `nix run .#release-notes -- <version> CHANGELOG.md` | Release notes for one version |

## Repository layout

```text
modules/aspects/      base, capability, hardware, and role aspects
modules/profiles.nix  profile composition and published tags
modules/operations.nix checks, delivery, and GitHub operation graph
modules/schema/       typed entities and classes
npins/sources.json    immutable upstream container source lock
bootc/builder/        full, derived, planning, and reuse engines
lib/                  Flake checks, applications, and artifact rendering
home/                 shared Home Manager modules
installer/            installer container and root filesystem
automation/           GitHub policy and release helpers
tests/                focused repository and build contracts
```

See [Troubleshooting](troubleshooting.md) for failed checks and local build
diagnostics.
