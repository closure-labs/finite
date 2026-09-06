#!/usr/bin/env bash
set -euo pipefail
# Fix build account IDs before Fedora's Nix RPM scriptlets run.
systemd-sysusers "${CONFIG_DIRECTORY}/system/usr/lib/sysusers.d/finite-nix.conf"
