#!/usr/bin/env bash
set -euo pipefail

state=${1:-/var/lib/finite-vm}
[[ ! -e "$state/predecessor-labels-prepared" ]] || exit 0
echo 'Preparing historical predecessor Nix and home policy before Nix startup'
FINITE_HOME_CONTEXTS_COMMAND="$state/fix-home-contexts" \
  bash "$state/install-nix-policy"
touch "$state/predecessor-labels-prepared"
