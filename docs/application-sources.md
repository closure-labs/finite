# Application sources

Finite uses Nix and Home Manager as the primary source of applications and user
settings. Bluefin also supplies its system tools, Flatpak integration and
Homebrew environment.

## Choose where to add an app

| Need | Configuration |
| --- | --- |
| A curated role or optional package | `finite-configure` |
| An additional Nix package | `home.packages` in `customize.nix` |
| A Flathub application | `services.flatpak.packages` in `customize.nix` |
| A Bluefin or local Homebrew tool | The corresponding Brew configuration |

Finite prefers the pinned chilled Nixpkgs set. Selected applications use the
weekly set where that provides the required package or version. See
[Configure your environment](configuration.md#add-packages-and-personal-settings)
for examples.

## Identify the active command

A command may be available from several providers. Inspect the current shell:

```bash
command -v git
command -v jq
finite-brew-migration-status
```

The status report shows requested Homebrew packages and their active providers.
An `ACTIVE_PROVIDER` beginning with `nix:` identifies a Nix command. Check its
behavior in a fresh login shell before changing a duplicate installation.

Home Manager places its packages early on `PATH`. Existing Homebrew packages
remain available, including Bluefin's shell integration. In particular,
Bluefin sources its Homebrew `bash-preexec` script directly.

## Review local choices

List explicitly requested formulas and casks with:

```bash
brew leaves --installed-on-request
brew list --cask
```

Use this inventory alongside `customize.nix` when managing local additions such
as AWS CLI or Codex. Keep the configuration and application data needed to
restore a package if you change its provider.
