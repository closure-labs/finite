# Configure foundations, hardware, and roles

Finite separates the immutable bootc foundation from a per-user Home Manager
composition:

```text
foundation: bluefin | bluefin-dx
hardware:   generic-x86_64 | dell-xps-9350-intel
roles:      any subset of developer, sales, trainer, support, executive, it
```

The running image records explicit `foundation` and `hardware` fields in
`/usr/share/finite/profile.json`. First-login and `finite-configure` treat those
fields as authoritative; a YAML seed for a different image is rejected.

## Profile data

Provisioning uses YAML. Bootstrap normalizes it to JSON:

```json
{
  "schema": 1,
  "foundation": "bluefin-dx",
  "hardware": "dell-xps-9350-intel",
  "roles": ["developer", "support"],
  "identity": {
    "username": "dale",
    "homeDirectory": "/var/home/dale"
  }
}
```

The account values are discovered with `id` and `getent`. Supplied identity
values must match. Unknown or duplicate roles, unknown foundations or hardware,
extra schema fields, malformed documents, and running-image mismatches fail
before any deployed file changes.

The normalized profile lives at `~/.config/finite/profile.json`. The standalone
flake, its copy of the normalized profile, and its remote lock live under
`~/.config/home-manager`. `nh home switch --update-input finite` updates only
the Finite input. `finite-configure` reopens the role checklist with current
roles selected and activates only after a successful build.

## Templates and bootstrap

```console
nix flake new -t github:closure-labs/finite#home-bluefin PATH
nix flake new -t github:closure-labs/finite#home-bluefin-dx PATH
```

Both templates expose `home-profile` and `home-bootstrap` before a profile has
been configured. The deployed flake imports the focused
`finite.flakeModules.home`, declares one `den.homes` entity, and composes a local
aspect from the Finite base, selected role aspects, and selected hardware.

To convert a supplied legacy named-profile JSON document whose data includes
`foundation` (or `baseClass`), `hardware`, and `roles`:

```console
nix run github:closure-labs/finite#home-bootstrap -- \
  --legacy-profile ./exported-profile.json
```

The importer is generic: it does not look in former runtime paths or expose a
named-preset registry.

## Catalog and aspects

```console
nix build .#generated
jq . result/bootc/generated/home-profile-catalog.json
```

The schema-2 catalog contains typed `foundations`, `hardware`, `roles`, and
`compatibility` maps. Aspect implementations live below
`modules/aspects/{base,capabilities,hardware,roles}`. Add a role to
`finite.home.roles` in `modules/profiles/definitions.nix`, give it a stable
ordering key, and validate every foundation with `just check`.
