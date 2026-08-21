# Customize profiles and aspects

Purplefin separates the system foundation from user roles. Four typed Den
profiles produce lightly layered bootc images; eight typed Home Manager
profiles provide applications and preferences. Nix resolves both registries
into CI matrices, catalogs, activation packages, and installer Blueprints.

## Profile graph

```text
Bluefin ──┬── generic-x86_64
         └── dell-xps-9350-intel

Bluefin DX ──┬── generic-x86_64
            └── dell-xps-9350-intel

Home Manager
├── Bluefin: sales, executive
└── Bluefin DX: developer, support, it, trainer
    ├── dale: every role combined, Dell XPS 13 9350 only
    └── elad: every role combined, generic x86-64 without the Dell camera layer
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
contains its Den declaration and focused tests. Base and hardware features may
also carry an image build step; role features are Home Manager modules:

```text
modules/aspects/roles/support/
├── default.nix
└── tests/
```

`default.nix` declares the aspect and its Home Manager configuration. Keep
files consumed by a module in the same feature directory. Only system and
hardware necessities belong in bootc source closures.

## Add a profile

In `modules/profiles/definitions.nix`:

1. Add a Home Manager aspect that includes the base and desired roles.
2. Add the matching `purplefin.homeProfiles` entity with its required
   `baseClass`, supported hardware, and ordered roles.

Validate and inspect it:

```bash
nix shell --accept-flake-config .#ci-check -c purplefin-ci-check
nix build .#generated
jq '.profiles["your-profile"]' \
  result/bootc/generated/home-profile-catalog.json
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
