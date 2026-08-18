# Customize profiles and aspects

Purplefin models each final image as a typed Den profile. Profiles include a
parent profile and reusable aspects; Nix resolves the graph into ordered bootc
steps, Home Manager configurations, CI matrices, catalogs, and installer
Blueprints.

## Profile graph

```text
base
├── base-generic
│   ├── developer-generic
│   ├── executive-generic
│   ├── it-generic
│   ├── sales-generic
│   ├── support-generic
│   └── trainer-generic
└── base-dell-xps-9350-intel
    ├── dale
    ├── sales-dell-xps-9350-intel
    └── support-dell-xps-9350-intel
```

Inspect the evaluated graph and catalog:

```bash
nix build .#architecture
less result/architecture.md

nix build .#generated
jq '.profiles' result/bootc/generated/profile-catalog.json
```

## Change an aspect

Aspects live below `modules/aspects/<namespace>/<name>/`. A feature directory
contains its Den declaration, build step, payload, and focused tests:

```text
modules/aspects/roles/support/
├── default.nix
├── apply.sh
├── manifests/
├── rootfs/
└── tests/
```

`default.nix` declares the aspect, ordered bootc steps, source inputs, and any
Home Manager modules. Keep files consumed by a step in the same feature
directory and include every consumed path in its source closure.

## Add a profile

In `modules/profiles.nix`:

1. Add a profile aspect whose `includes` list composes its parent and features.
2. Add the matching `purplefin.profiles` entity with its parent and published
   tags.

Validate and inspect it:

```bash
nix run .#ci
nix build .#generated
jq '.profiles["your-profile"]' \
  result/bootc/generated/profile-catalog.json
```

## Add an aspect

Create the aspect in one of these namespaces:

- `modules/aspects/capabilities/`
- `modules/aspects/hardware/`
- `modules/aspects/roles/`

Register it as `den.aspects.features.<namespace>.<name>` and include it from a
profile or another feature. The typed bootc class declares its build steps and
source paths.

## Runtime configuration

Hardware-specific overrides are documented in
[Dell XPS 13 9350](dell-xps-9350.md). Purplefin also provides a session-scoped
lid inhibitor for AC-powered laptop use:

```bash
purplefin-caffeinate on
purplefin-caffeinate status
purplefin-caffeinate off
```

Register a FIDO2/U2F key for PAM authentication with:

```bash
mkdir -p ~/.config/Yubico
pamu2fcfg >~/.config/Yubico/u2f_keys
```
