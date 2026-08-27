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

Provisioning accepts YAML or JSON. `finite-home-init` normalizes it to JSON:

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

The normalized profile lives at `~/.config/finite/profile.json`. The complete
standalone flake lives at `~/.config/home-manager`: its Den module, every Finite
Home Manager aspect, referenced assets, helper scripts, profile, and pinned
third-party input lock are all local to that directory. It has no `finite`
input and no path back to a source checkout. Run `nh home switch` to rebuild it,
or `nix flake update ~/.config/home-manager` to refresh its independent pinned
inputs. `finite-configure` reopens the role checklist with current roles
selected and activates only after a successful build.

## Self-contained templates and initialization

```console
nix flake new -t github:closure-labs/finite#home-manager PATH
nix flake new -t github:closure-labs/finite#home-bluefin PATH
nix flake new -t github:closure-labs/finite#home-bluefin-dx PATH
```

All three names expose the same canonical, complete template. The two
foundation-specific names are compatibility aliases; bootstrap does not select
a different template tree. Instead it writes the normalized foundation,
hardware, roles, and account identity to the generated flake's local
`profile.json`. `modules/finite.nix` reads those variables and uses Den's
standalone `den.homes` output to compose the matching local aspects.

On Finite, `/usr/libexec/finite/home-init --profile PROFILE` copies the image's
pinned template to a staging directory, injects the account identity and
canonical role order, and builds it without changing the lock. Only a
successful build is installed. Any existing missing, partial, invalid, or
older scaffold is moved to a timestamped `home-manager.previous.*` directory
and the complete staged directory takes its place. The first-login service
compares the installed template marker with the image marker, so the same path
also performs simple release-to-release replacement.

## Catalog and aspects

```console
nix build .#generated
jq . result/bootc/generated/home-profile-catalog.json
```

The schema-2 catalog contains typed `foundations`, `hardware`, `roles`, and
`compatibility` maps. Bootc aspect implementations live below
`modules/aspects/{base,capabilities,hardware,roles}`. The canonical portable
Home Manager modules and assets live below
`templates/home-manager/modules/aspects`; that same tree is copied intact into
the final flake. Add a role to `lib/domain-catalog.nix`, give it a stable
ordering key and label, add its aspect implementation, and validate every
foundation with `just check`. The same pure catalog drives module enums,
profile ordering, generated catalogs, Home Manager proofs, and the
`finite-configure` checklist.
