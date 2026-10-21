# Application sources

Finite uses Home Manager for user settings and profile composition. Shared
command-line tools use Bluefin's Homebrew installation; the remaining curated
applications use Nix or Flatpak.

## Choose where to add an app

| Need | Configuration |
| --- | --- |
| A curated role or optional package | `finite-configure` |
| An additional Nix package | `home.packages` in `customize.nix` |
| A Flathub application | `services.flatpak.packages` in `customize.nix` |
| A Bluefin or local Homebrew tool | The corresponding Brew configuration |

For Nix applications, Finite prefers the pinned chilled Nixpkgs set. Selected
applications use the weekly set where that provides the required package or version. See
[Configure your environment](configuration.md#your-personal-configuration)
for examples.

## Shared CLI tools use Homebrew

The common profile uses Homebrew for these tools on every foundation and role:

`atuin`, `bash-preexec`, `bat`, `bbrew`, `chezmoi`, `direnv`, `dysk`, `eza`, `fd`,
`gh`, `mise`, `podman-tui`, `ripgrep`, `starship`, `tealdeer`, `trash-cli`,
`ugrep`, `uutils-coreutils`, `yq` and `zoxide`.

The provider list is maintained in
[`brew-packages.json`](https://github.com/closure-labs/foundation/blob/main/modules/aspects/base/brew-packages.json).
Home Manager generates `~/.config/finite/Brewfile` from it. These tools are no
longer installed as top-level Nix profile packages. Nix-only applications,
including `fzf`, `jj`, `uv`, Neovim and Marp, retain their existing providers.
`nh` remains enabled in the shared Home Manager base profile for everyone.
Finite's helper scripts and build tools retain their pinned Nix dependencies.

`finite-home-init` and `finite-home-apply` build the requested generation first,
then install any missing shared Brew tools before changing the Home Manager
configuration. Their `--check` mode builds without installing anything.
Provisioning uses `brew bundle install --no-upgrade` and does not remove other
Brew packages. Bluefin's `brew-setup.service` must have initialized Homebrew.

Direct Home Manager activation checks the Brew alternatives before changing
the generation. If they are missing, it stops and prints an install command
using the generated Brewfile. Follow that command, then retry activation. For
an already configured profile, the equivalent command is:

```bash
brew bundle install --no-upgrade --file="${XDG_CONFIG_HOME:-$HOME/.config}/finite/Brewfile"
```

## Identify the active command

A command may be available from several providers. Inspect the current shell:

```bash
command -v git
command -v jq
finite-brew-migration-status
finite-brew-migration-status --check
```

The read-only report checks every shared tool, including missing formulas and
commands shadowed by another provider. `--check` exits unsuccessfully unless
every shared tool resolves to Homebrew. `--check-installed` checks the Brew
alternatives directly, even while an older Nix generation still shadows them.
Run the active-provider check in a fresh login shell after applying the profile;
it inspects inherited `PATH`, not interactive aliases or functions.

Home Manager still owns Zsh, its plugins and Fzf integration. Every profile puts
Homebrew's uutils directory and executable directories first in interactive
Zsh, so host copies of tools such as Starship and `yq` cannot shadow the chosen
Brew providers. Bluefin continues to source Homebrew's `bash-preexec` file directly.

Apply the updated Home Manager configuration to remove old Nix profile
duplicates. Do not remove the entire `home-manager-path` package or uninstall
Brew alternatives. Old Nix generations remain available for rollback until
you deliberately expire them; their store paths are not active duplicates.

## Keep applications current

First-login uses the image's Foundation catalog for role labels and ordering.
When available, its Professional classification is shown beside each work role.
Saved selections take precedence over provisioning seeds; invalid or unsupported
profiles produce an error instead of a replacement selection. Existing complete
personal consumers are left to their own update workflow. Seed and fresh-login
writers continue to emit schema 2.

The reader dispatcher also preserves supplied schema-3 selections when the
executing Foundation helper advertises initialization support. An older helper
rejects that selection without falling back to a seed or opening the fresh
selector. Fresh-login and cloud-init generators remain schema 2; the installed
Foundation pin determines which newer formats can actually be read.

Foundation releases own the managed Home Manager modules and dependency pins.
OS updates do not overwrite the installed personal flake. Inspect published
Foundation release availability with:

```bash
finite-app-status
finite-app-status --json
finite-home-update --check
```

Run `ujust update` or `finite-home-update` to stage, build and apply a supported
published release. Background notifications open a read-only review window when
clicked; they do not activate updates. Drafts, prereleases and older releases
are excluded. New personal consumers also support `nh home switch -u` through
Foundation's `latest-release` branch; the lock still pins the exact published
source. See [configuration and migration](configuration.md).

Declare personal Git sources in local modules with explicit commits and content
hashes. These snapshots are independent of Foundation's flake inputs and advance
only when their declarations change and Home Manager is applied.

Homebrew and Flatpak have separate update paths:

```bash
brew update
brew outdated
brew upgrade
flatpak update --user
flatpak update --system
```

Run Homebrew as its owning desktop user, not root. The inherited Bluefin units
include `brew-update.timer` and `brew-upgrade.timer`; the latter's service has a
storage-layout condition, so an installed timer alone does not prove updates
run. Check `systemctl status brew-update.timer brew-upgrade.timer` and
`journalctl -u brew-upgrade.service`. Bluefin's `ujust update` also includes
Flatpak/Homebrew update paths. Inspect `systemctl status uupd.timer` and the
actual service logs on your image before relying on inherited automation.
Finite's Home Manager Flatpak auto-update remains disabled; verify system and
user Flatpak installations separately. The workstation owner is responsible
for reviewing and applying app updates.

## Review local choices

List explicitly requested formulas and casks with:

```bash
brew leaves --installed-on-request
brew list --cask
```

Use this inventory alongside `customize.nix` when managing local additions such
as AWS CLI or Codex. Keep the configuration and application data needed to
restore a package if you change its provider.
