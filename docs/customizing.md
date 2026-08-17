# Customizing Purplefin

Purplefin models each final operating-system image as a typed Den profile
entity. A profile points at an aspect, and profile aspects include parent
profiles plus reusable features. Nix resolves that graph into ordered image
build steps, exact deltas, Home Manager configurations, the CI matrix, and
OSBuild Blueprints.

## Profile graph

```text
base
├── base-generic
│   ├── sales-generic
│   ├── support-generic
│   ├── developer-generic
│   ├── trainer-generic
│   ├── executive-generic
│   └── it-generic
└── base-dell-xps-9350-intel
    ├── sales-dell-xps-9350-intel
    ├── support-dell-xps-9350-intel
    └── dale
```

The common base starts from Bluefin Stable. Hardware features add the shared
security baseline and model behavior. Role features add workloads to a
hardware parent. `dale` combines sales, training, and support features on the
Dell hardware parent.

## Change an existing feature

A feature owns its declaration, image step, payload, manifests, and focused
tests below `modules/aspects/`. For example, support is contained in:

```text
modules/aspects/roles/support/
├── default.nix
├── apply.sh
├── manifests/
└── rootfs/
```

`default.nix` registers the feature in `den.aspects.features`, declares its
ordered bootc step and complete source-input closure, and may provide Home
Manager modules. `apply.sh` performs the image mutation and consumes only the
payload beside it. This makes ownership and build invalidation visible from a
single directory.

## Add a profile

Add both parts to `modules/profiles.nix`:

- a profile aspect whose `includes` compose its parent and features;
- a typed `purplefin.profiles` entity with its parent and published tags.

The parent supplies the inherited feature stack. Features introduced at the
new node become its exact derived-image delta. Validate the result with:

```bash
nix flake check --print-build-logs
nix build .#generated
jq '.profiles["your-profile"]' result/bootc/generated/profile-catalog.json
```

## Add a reusable feature

Create a directory in the appropriate namespace:

- `modules/aspects/capabilities/<name>/`
- `modules/aspects/roles/<name>/`
- `modules/aspects/hardware/<name>/`

Register `den.aspects.features.<namespace>.<name>` in `default.nix`. Declare
every ordered build step and every source path it consumes through the typed
bootc class. Put the implementation and assets in the same directory, then
include the feature from profile or feature aspects.

## Inspect the architecture

The architecture package renders the live Den aspect namespace rather than a
hand-maintained diagram:

```bash
nix build .#architecture
less result/architecture.md
```

Generated catalogs and installer Blueprints remain Nix store outputs. Use
`nix run .#export-artifacts` only when a container or other filesystem-oriented
consumer needs materialized files.
