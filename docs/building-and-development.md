# Building and development

Purplefin uses its Nix Flake as the repository control plane. Enter the pinned
development environment with:

```bash
nix develop
```

## Validate the repository

Run the complete check graph while editing or before publishing:

```bash
nix fmt
nix flake check --print-build-logs
```

The graph validates formatting, the typed Den profile model, generated
artifacts, every Home Manager configuration, shell code, repository contracts,
hardware behavior, GitHub Actions, and security policy. `nix run .#ci` is the
interactive form of the repository check, and `just check` is a short alias.

## Build an image

The image-build app resolves the configured upstream image to an immutable
digest, materializes the generated build contract, and invokes Podman:

```bash
nix run .#image-build -- base-generic localhost/purplefin:base-generic
nix run .#image-build -- dale localhost/purplefin:dale
```

The profile name must exist in the typed registry in `modules/profiles.nix`.
The build engine executes the ordered steps declared by the profile's resolved
Den aspects.

## Generated artifacts

Catalogs and OSBuild Blueprints are derivations, not checked-in source:

```bash
nix build .#generated
find -L result -type f -print
```

Tools that require ordinary filesystem paths can materialize the derivation in
an ignored directory:

```bash
nix run .#export-artifacts
# or, for CI/container consumers expecting repository-relative paths:
nix run .#export-artifacts -- .
```

The output contains:

- `bootc/generated/image-matrix.json`
- `bootc/generated/profile-catalog.json`
- `bootc/generated/upstream.json`
- `installer/config/profiles/*.toml`

## Useful Flake outputs

```bash
nix build .#generated
nix build .#architecture
nix build .#home-dale
nix build .#syft
nix build .#sbomnix
nix run .#release-notes -- 0.2.0 CHANGELOG.md
nix run .#classify-changes -- images
nix run .#image-plan -- "$(jq -c . result/bootc/generated/image-matrix.json)"
nix run .#installer-smoke -- output/purplefin.iso
```

`generated` is the machine-consumable architecture contract. `architecture`
renders the actual Den aspect namespace as Mermaid. Each `home-*` package is a
Home Manager activation package for a profile. The remaining applications pin
the tools used at CI/CD and host-capability boundaries.

## Hermetic boundary

Source-derived architecture, generated IaC, tests, workflow policy, and
security linters are declared by the Flake and evaluated by
`nix flake check`. GitHub event routing, protected environments, OIDC
attestations, registry credentials, and container or VM execution remain thin
platform boundaries because they require mutable remote state or host
capabilities. Shell under an aspect implements that aspect inside the image;
it is not a manual orchestration API.

## Source layout

```text
modules/aspects/     Den features with their build step, payload, and local tests
modules/schema/      typed entity and class schemas
modules/policies/    Den resolution policies
modules/classes/     class-specific option declarations
modules/profiles.nix profile aspect DAG and typed profile registry
bootc/builder/       generic full, derived, planning, and reuse engines
lib/                 graph evaluation and artifact rendering
home/                shared Home Manager modules
installer/           Image Builder container and installer root filesystem
automation/          thin release and GitHub platform boundary scripts
tests/                repository, automation, bootc, and installer contracts
```
