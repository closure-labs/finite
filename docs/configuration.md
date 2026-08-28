# Configure foundations, hardware, and roles

Finite separates the immutable bootc foundation from a per-user Home Manager
composition:

```text
foundation: bluefin | bluefin-dx
image:      generic-x86_64 | next-x86_64
home:       generic-x86_64 | dell-xps-9350-intel
roles:      any subset of developer, sales, trainer, support, executive, it
packages:   any subset of hack-font, herdr, jj, opencode, uv
```

The running image records explicit `foundation` and image `hardware` fields in
`/usr/share/finite/profile.json`. A user's profile records the selected Home
Manager hardware aspect instead. First-login keeps the foundation authoritative
and accepts only Home Manager hardware declared compatible with the running
generic or next image. On an XPS 13 9350 it selects the Dell Home Manager aspect
automatically; that aspect does not change the boot image or camera stack.

## Profile data

Provisioning accepts YAML or JSON. `finite-home-init` normalizes it to JSON:

```json
{
  "schema": 2,
  "foundation": "bluefin-dx",
  "hardware": "dell-xps-9350-intel",
  "packages": ["jj", "uv"],
  "roles": ["developer", "support"],
  "identity": {
    "username": "dale",
    "homeDirectory": "/var/home/dale"
  }
}
```

The account values are discovered with `id` and `getent`. Supplied identity
values must match. Unknown or duplicate packages or roles, unknown foundations
or hardware, incompatible image/Home Manager hardware pairs, extra schema
fields, malformed documents, and running-foundation mismatches fail before any
deployed file changes. Schema-1 profiles remain valid initializer input and are
normalized to schema 2 with an empty package selection.

The normalized profile lives at `~/.config/finite/profile.json`. The complete
standalone flake lives at `~/.config/home-manager`: its Den module, every Finite
Home Manager aspect, referenced assets, helper scripts, profile, and pinned
third-party input lock are all local to that directory. It has no `finite`
input and no path back to a source checkout. Run `nh home switch` to rebuild it,
or `nix flake update --flake ~/.config/home-manager` to refresh its independent pinned
inputs. `finite-configure` opens graphical role and optional-package checklists
with the current selections preselected and activates only after a successful
build.

The flake exports `homeConfigurations.<username>`, where `<username>` is the
validated local account recorded during installation or first login. This
matches `nh`'s automatic Home Manager configuration lookup, so no `-c` argument
is required.

## Add your own packages and Flatpaks

Edit `~/.config/home-manager/customize.nix`. It is a normal additive Home
Manager module imported after Finite's generated modules. Finite preserves this
file, along with `modules/local.nix`, when an image update replaces the rest of
the generated scaffold.

```nix
{inputs, pkgs, ...}: {
  home.packages =
    (with pkgs; [
      jq
    ])
    ++ [
      inputs.nixpkgs-weekly.legacyPackages.${pkgs.stdenv.hostPlatform.system}.example
    ];

  services.flatpak.packages = [
    "org.gimp.GIMP"
  ];
}
```

Use the weekly half of the list only when the chilled package set lacks what
you need or a newer version is deliberately required.

List-valued options such as `home.packages` and `services.flatpak.packages`
merge with Finite's lists; they do not replace the generated module. Validate
the result before activation with `nh home build`, then apply it with
`nh home switch`.

The entries in `home.packages` are Nix derivations from the pinned chilled or
weekly Nixpkgs inputs. They are not Homebrew package names or representations
of Homebrew state. Homebrew may still contain a second copy during the staged
migration, but the Nix profile normally appears first on `PATH`.

## Graphical package management

`finite-configure` is the supported graphical interface for Finite's curated
roles and optional Nix packages. Arbitrary additions remain declarative in
`customize.nix`; Flathub applications can also be explored graphically with
Bluefin's Flatpak software tools and then recorded by application ID in that
file.

General Nix GUIs exist, but they do not edit Finite's standalone Home Manager
module safely. [Nix Software Center](https://github.com/snowfallorg/nix-software-center)
targets `configuration.nix` or imperative `nix profile` installs, while
[Nix-Gui](https://github.com/nix-gui/nix-gui) describes itself as a work in
progress for NixOS configurations. Finite does not install either in the base
environment.

## Self-contained templates and initialization

```console
nix flake new -t github:closure-labs/finite#home-manager PATH
nix flake new -t github:closure-labs/finite#home-bluefin PATH
nix flake new -t github:closure-labs/finite#home-bluefin-dx PATH
```

All three names expose the same canonical, complete template. The two
foundation-specific names are compatibility aliases; bootstrap does not select
a different template tree. Instead it writes the normalized foundation,
hardware, packages, roles, and account identity to the generated flake's local
`profile.json`. `modules/finite.nix` reads those variables and uses Den's
standalone `den.homes` output to compose the matching local aspects.

On Finite, `/usr/libexec/finite/home-init --profile PROFILE` copies the image's
pinned template to a staging directory, preserves the two customization
modules, injects the account identity and canonical package and role order, and
builds it without changing the lock. Only a successful build is installed. Any
existing missing, partial, invalid, or older scaffold is moved to a timestamped
`home-manager.previous.*` directory and the complete staged directory takes its
place. The first-login service compares the installed template marker with the
image marker, so the same path also performs simple release-to-release
replacement.

## Catalog and aspects

```console
nix build .#generated
jq . result/bootc/generated/home-profile-catalog.json
```

The schema-3 catalog contains typed `foundations`, `hardware`, `packages`,
`roles`, and `compatibility` maps. Bootc aspect implementations live below
`modules/aspects/{base,capabilities,hardware,roles}`. The canonical portable
Home Manager modules and assets live below
`templates/home-manager/modules/aspects`; that same tree is copied intact into
the final flake. Add a role to `lib/domain-catalog.nix`, give it a stable
ordering key and label, add its aspect implementation, and validate every
foundation with `just check`. The same pure catalog drives module enums,
profile ordering, generated catalogs, Home Manager proofs, and the
`finite-configure` checklist.
