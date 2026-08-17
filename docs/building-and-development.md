# Building and development

Purplefin's pinned Nix development shell supplies `actionlint`, `just`,
`ripgrep`, `shellcheck`, `treefmt`, `zizmor`, PipeWire tools, and Zsh:

```bash
nix develop
```

## Repository checks

Run the complete hermetic validation graph while editing or before publishing:

```bash
nix flake check --print-build-logs
```

Refresh generated artifacts explicitly when the profile model changes, then run
the same check graph used by CI:

```bash
nix run .#generate
nix fmt
nix flake check --print-build-logs
```

`nix flake check` owns formatting, generated-file consistency, profile schema,
every Home Manager configuration, repository policy, shell validation,
workflow linting, security linting, graph tests, installer tests, and hardware
tests. CI invokes that single graph instead of manually composing test scripts.
`nix run .#ci` runs the repository-check application directly when an
interactive, non-sandboxed diagnostic run is useful. `just check` is retained
only as a compatibility alias for the Flake check graph.

Use `just format-check` for a read-only formatting check.

## Build an image

The common local recipes build the primary profiles:

```bash
just build-generic
just build-dell
just build-base-generic
just build-support-dell
```

The matching `lint-*` recipes validate the Containerfile stages. Run
`just --list` for the current recipe list.

A direct build resolves Bluefin to an immutable digest and passes the selected
profile to the Containerfile:

```bash
base_digest="$(
  skopeo inspect \
    --format '{{.Digest}}' \
    docker://ghcr.io/projectbluefin/bluefin:stable
)"

podman build \
  --build-arg BASE_REF="ghcr.io/projectbluefin/bluefin@${base_digest}" \
  --build-arg BUILD_PROFILE=dale \
  --build-arg PURPLEFIN_VERSION="$(<VERSION)" \
  --tag localhost/purplefin:dale \
  .
```

## Generated files

The Den profile model generates:

- `bootc/generated/image-matrix.json`
- `bootc/generated/profile-catalog.json`
- `bootc/generated/upstream.json`
- `installer/config/profiles/*.toml`

Refresh them after changing a profile, aspect, or image-builder setting:

```bash
nix run .#generate
```

Set `PURPLEFIN_SOURCE_ROOT` when generating into another checkout. The normal
workflow runs the command from the repository root.

## Useful flake outputs

```bash
nix build .#generated
nix build .#home-dale
nix build .#syft
nix build .#sbomnix
nix run .#release-notes -- 0.2.0 CHANGELOG.md
nix run .#changed-component -- images
nix run .#image-build -- base-generic localhost/purplefin:base-generic
nix run .#installer-smoke -- output/purplefin.iso
```

`generated` contains all generated catalogs and Blueprints. Each `home-*`
package is a Home Manager activation package for a named profile. Syft creates
the published bootc SPDX documents, while sbomnix can describe native Nix
closures. The Flake apps pin the toolchains for CI policy, release-note
extraction, change classification, immutable image planning/reuse, and local
Podman builds.

## Hermetic boundary

Source-derived architecture, generated IaC, tests, workflow policy, and
security linters are declared in the Flake and evaluated by `nix flake check`.
GitHub event routing, protected environments, OIDC attestations, GHCR
credentials, and container/VM execution remain thin platform boundaries: they
require mutable remote state or host capabilities, but call Flake applications
where a pinned local toolchain is useful. Bash files under `bootc/` remain the
image's build/runtime implementation rather than a manual orchestration API.

## Source layout

```text
nix/aspects/          Den aspects and Home Manager customizations
nix/flake-modules/    profile composition and flake outputs
bootc/modules/        build-time implementation for each aspect
bootc/overlays/       base, role, and hardware filesystem content
bootc/components/     reusable multi-role components
bootc/build/          full, derived, and planning entrypoints
bootc/generated/      generated catalogs consumed by builds and CI
installer/            Image Builder environment, overlay, and Blueprints
tests/                local and CI validation entrypoints
```
