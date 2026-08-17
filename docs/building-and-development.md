# Building and development

Purplefin's pinned Nix development shell supplies `actionlint`, `just`,
`ripgrep`, `shellcheck`, `treefmt`, `zizmor`, PipeWire tools, and Zsh:

```bash
nix develop
```

## Repository checks

Run the fast repository checks while editing:

```bash
just check
```

Run the complete local validation before publishing a change:

```bash
nix run .#generate
just format
nix flake check
nix develop --command tests/ci.sh
```

`nix flake check` verifies formatting, generated files, the profile schema, and
every Home Manager configuration. `tests/ci.sh` runs the repository policy,
shell, workflow, graph, installer, and hardware tests used by CI.

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
```

`generated` contains all generated catalogs and Blueprints. Each `home-*`
package is a Home Manager activation package for a named profile. Syft creates
the published bootc SPDX documents, while sbomnix can describe native Nix
closures.

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
