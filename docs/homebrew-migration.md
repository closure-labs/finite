# Staged Homebrew migration

Finite treats Homebrew reduction as a sequence of reversible release layers.
The first layer adds and verifies Nix replacements; it does not uninstall any
formula, cask, tap, or Homebrew itself.

## Package ownership

Bluefin's current CLI bundle owns these requested formulas:

```text
atuin  bash-preexec  bat  bbrew  chezmoi  direnv  dysk  eza  fd  gh
mise  podman-tui  ripgrep  starship  tealdeer  trash-cli
uutils-coreutils  ugrep  yq  zoxide
```

Finite supplies Nixpkgs versions of every command in that list. Most come from
the pinned chilled package set; `bbrew` and `mise` use the pinned weekly set.
`bash-preexec` is also present in Nixpkgs, but Bluefin directly sources its
Homebrew profile script. Keep the Brew formula until that integration has a
tested Nix-aware fallback.

The current workstation also has requested Brew packages outside Bluefin's
bundle. Finite handles them as follows:

| Brew request | Finite layer | Policy in this release |
| --- | --- | --- |
| `fzf`, `marp-cli`, `neovim` | Base | Nixpkgs version is active; Brew stays as fallback |
| `herdr` | Optional package | Weekly Nixpkgs; select with `finite-configure` |
| `jj`, `opencode`, `uv` | Optional packages | Chilled Nixpkgs; select with `finite-configure` |
| Hack Nerd Font cask | Optional package | Chilled Nixpkgs plus Home Manager Fontconfig |
| Zsh autosuggestions, history search, syntax highlighting, and vi mode | Developer/Support capability | Home Manager modules and Nixpkgs own the active shell integration |
| `awscli`, Codex cask | Local customization | Deliberately absent from Finite; keep Brew until added in `customize.nix` |

Dependencies shown by `brew list --formula` are not separate migration choices.
Classify requested packages with `brew leaves --installed-on-request`, the
Bluefin Brewfile, and `brew list --cask`.

## Layers and gates

### Layer 0: Bluefin fallback

Homebrew and all current formulas remain installed. Bluefin can keep updating
its own bundle, and `ujust bluefin-cli` remains a recovery path.

### Layer 1: Nix shadows Brew

This is the implemented release layer. Home Manager installs the base Nix
commands and selected optional packages ahead of Homebrew on `PATH`. Run:

```console
finite-brew-migration-status
```

The command is read-only. A command is ready for a later removal layer only
when its `ACTIVE_PROVIDER` starts with `nix:` and its basic behavior has been
tested in a fresh login shell. Font and shell plugins require the additional
manual checks printed by the report.

### Layer 2: Remove workstation duplicates

In a later Finite release, remove only non-Bluefin Brew requests whose Nix
replacement has passed Layer 1. Do not remove AWS CLI or Codex until the local
`customize.nix` replacement builds and becomes active. Keep a record of the
removed requested formulas so they can be restored independently.

### Layer 3: Reduce the Bluefin CLI bundle

After at least one release of fallback coverage, remove Bluefin-requested
formulae one group at a time. Re-run the status report and shell smoke tests
after every group. Leave `bash-preexec` until last, and retain the Homebrew
installation itself while Bluefin owns shell setup, completion, update, and
recovery behavior around it.

### Layer 4: Reassess Homebrew itself

Only consider removing Homebrew after no Bluefin or local integration reads
its prefix and `ujust` recovery no longer depends on it. That is outside the
scope of this release.

## Rollback

During Layer 1, rollback is simply selecting the Brew command explicitly from
`/home/linuxbrew/.linuxbrew/bin` or switching to the previous Home Manager
generation. Future removal layers must restore a failed package before moving
on; they must not batch-remove the whole Brew prefix.
