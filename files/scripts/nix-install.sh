#!/usr/bin/env bash
set -euo pipefail
export FINITE_ASSET_ROOT="${CONFIG_DIRECTORY}/payload"
rpm -q cloud-init jq nix nix-daemon nix-filesystem nix-system yq zenity
install -m 0644 /usr/lib/sysusers.d/finite-nix.conf /usr/lib/sysusers.d/nix.conf
rm /usr/lib/sysusers.d/finite-nix.conf
rm -rf /run/cloud-init
bash "${CONFIG_DIRECTORY}/scripts/lib/install-determinate-nix.sh"
bash "${CONFIG_DIRECTORY}/scripts/lib/install-nix-systemd-units.sh"
