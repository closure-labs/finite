#!/usr/bin/env bash
set -euo pipefail

brew=${FINITE_BREW_COMMAND:-/home/linuxbrew/.linuxbrew/bin/brew}
export HOMEBREW_NO_AUTO_UPDATE=1
"$brew" tap valkyrie00/bbrew
"$brew" trust valkyrie00/bbrew

# The historical scaffold predates the longer activation wait. Model an
# existing user's additive configuration, which must survive update/rollback.
configuration="${XDG_CONFIG_HOME:-$HOME/.config}/home-manager"
mkdir -p "$configuration"
[[ ! -e "$configuration/customize.nix" ]] || {
  echo 'Predecessor fixture refuses to overwrite existing customization' >&2
  exit 1
}
cat >"$configuration/customize.nix" <<'NIX'
{ lib, ... }: {
  # VM acceptance customization: cold Flatpak downloads need more than 120s.
  systemd.user.servicesStartTimeoutMs = lib.mkForce (15 * 60 * 1000);
}
NIX
