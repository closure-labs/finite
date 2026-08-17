# Customizing Purplefin

Purplefin models each final operating-system image as a Den profile. Profiles
inherit a parent and include one or more aspects. Nix validates the graph and
generates the ordered build matrix, module deltas, catalog, Home Manager
configurations, and OSBuild Blueprints.

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

The common `base` starts from Bluefin Stable. Hardware profiles add the shared
security baseline and model-specific behavior. Role profiles add workload
features to a hardware parent. The `dale` profile combines sales, training,
and support features on the Dell hardware parent.

## Change an existing feature

Each reusable feature has a Den aspect under `nix/aspects/<name>/`. Its bootc
implementation lives in the matching `bootc/modules/<name>.sh`, with files and
manifests under `bootc/overlays/` or `bootc/components/`.

For example, the support aspect connects:

```text
nix/aspects/support/default.nix
bootc/modules/support.sh
bootc/overlays/roles/support/
```

Edit the aspect when profile or Home Manager composition changes. Edit the
bootc module, overlay, or component when the operating-system image changes.

## Add a profile

Add one definition to `nix/flake-modules/profiles.nix` with:

- a unique profile name;
- an existing parent;
- the aspects introduced at that node;
- one or more published tags.

The parent supplies its full aspect stack. The new node's `includes` list
becomes its exact build delta, which allows CI to reuse the immutable parent
image.

Refresh and validate the graph:

```bash
nix run .#generate
nix flake check
nix develop --command tests/ci.sh
```

## Add a reusable aspect

Create `nix/aspects/<name>/default.nix` for the bootc feature metadata. Add
`home.nix` when the feature contributes a Home Manager module. Implement its
image changes in `bootc/modules/<name>.sh` and keep payload files beside their
ownership boundary in an overlay or reusable component.

Reference the new aspect from one or more profile definitions, regenerate the
catalog, and run the full validation sequence.

## Customize installer filesystems and users

Profile options can generate Image Builder Blueprint settings for `/`, `/boot`,
and supported bootc users. The generated Blueprints live in
`installer/config/profiles/`. Operating-system packages and services are
composed in the bootc modules so the installed payload matches the published
image digest.
