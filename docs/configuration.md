# Configure your environment

[Foundation](https://github.com/closure-labs/foundation) owns Finite's Home Manager
configuration, profile catalog and user helpers. Finite installs Nix, validates
host compatibility and provisions a personal consumer of a reviewed Foundation
release. Foundation has its own releases and tested dependency lock.

## Your personal configuration

`~/.config/home-manager/` contains a small flake importing Foundation, its lock,
`foundation.json` release provenance, `profile.json`, `customize.nix` and
`modules/local.nix`. Shared modules stay in the pinned Foundation source.

Use `finite-configure` to choose roles and optional packages. Edit
`customize.nix` or `modules/local.nix` for personal settings. These Home Manager
modules receive Foundation's `inputs`, `pkgs` and `finiteHomeAssets`, plus any
additional inputs explicitly declared in your personal flake.

```nix
{pkgs, ...}: {
  home.packages = [pkgs.jq];
  services.flatpak.packages = ["org.gimp.GIMP"];
}
```

`nh home build` builds personal changes and `nh home switch` activates them.
Keep `home.stateVersion` unchanged when updating. Keep your personal modules,
profile, flake and lock together in your own Git repository.

## Update Foundation

New personal flakes track `github:closure-labs/foundation/latest-release`.
The branch advances only to published stable releases with passing CI;
`flake.lock` records the exact source and dependency pins. `nh home switch -u`
updates all personal flake inputs and activates the result. Use
`nh home switch -U foundation` to update only Foundation, or `nh home switch`
to apply changes while keeping the existing lock. The lock is authoritative if
`foundation.json` still describes an earlier release after an NH update.

Existing fixed-commit consumers can opt in by changing their Foundation URL in
`flake.nix` to `github:closure-labs/foundation/latest-release` and updating that
input. Existing configurations are never rewritten at login.

Run `finite-home-update --check` to inspect published releases. Run
`finite-home-update`, or `ujust update`, to stage, build and apply the latest
supported published release. Drafts, prereleases and older versions are excluded.
Foundation's own tested dependency closure advances with its release; personal
inputs and local modules remain yours.

The updater runs as the desktop user with a 3 GiB memory limit, one build job
and one core. Larger profiles can explicitly set
`FOUNDATION_BUILD_MEMORY_MAX=5G finite-home-update`. These limits and backups
belong to the staged updater; direct NH commands use NH's build and activation
path. Failed builds leave the installed configuration in place. Successful
updates keep a `home-manager.previous.*` backup. If activation fails, it restores
the configuration and attempts to reactivate the previous generation. Homebrew
and Flatpak side effects cannot all be undone by this rollback.

Background checks can display a clickable release notification; they do not
activate updates. `finite-app-status --json` reports release availability and
`finite-app-status --review` opens the review window. An OS update or graphical
login does not overwrite an existing user's configuration or select another
Foundation release. Bluefin's root `uupd` timer remains separate from the explicit
user update step.

## Migrate the former copied template

Run `finite-home-migrate --check` to build a candidate without installation, then
`finite-home-migrate` to migrate and activate it. Migration adopts Foundation's
tested dependency pins, which can select older snapshots than personal pins.
It preserves the account profile, personal modules and additional flake inputs.

Modified upstream files, custom flake output functions, Git checkouts and symlink
roots require manual review. Migration stops rather than discarding those changes.
The previous configuration and Home Manager generation remain available for rollback.
Until migrated, existing configurations remain usable and login leaves them alone.

The migration command is also available from a published Foundation release:

```bash
nix run github:closure-labs/foundation/v0.2.0#home-migrate -- --check
```

## Git-backed Espanso snapshots

Keep private repository URLs, commit hashes and content hashes in your personal
`modules/local.nix`. Home Manager can fetch pinned Git snapshots and link selected
files into Espanso's configuration directory without custom template inputs.
See [Foundation's snapshot workflow](https://github.com/closure-labs/foundation/blob/main/docs/ESPANSO.md).
Workstation-specific Espanso declarations and files are never Foundation defaults.

## Host permissions and provisioning

The Support role includes Espanso's Wayland backend. A host administrator must
explicitly grant keyboard access with `sudo finite-keyboard-access enable`.
Inspect it with `finite-keyboard-access status`; revoke it with
`sudo finite-keyboard-access disable` followed by a reboot. Access applies to
programs running as active local seat users, rather than only Espanso.

For non-NixOS graphical apps, run the generated `non-nixos-gpu-setup` helper after
first activation as instructed by Home Manager. Finite's GPU boot integration
continues restoring the driver links.

`/usr/libexec/finite/home-init --profile PROFILE` provisions a new user's
configuration from the image's pinned Foundation source. The existing YAML/JSON
profile schema and cloud-init seed interface remain available. The initializer
validates the invoking account and host compatibility, builds before installing,
and leaves existing configurations to the explicit migration and update commands.
