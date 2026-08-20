#!/usr/bin/env bash
set -euo pipefail

aspect_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
module="${aspect_root}/default.nix"

grep -qF 'espanso = config.lib.nixGL.wrap pkgs.espanso' "${module}"
grep -qF 'services.flatpak.packages = ["io.github.totoshko88.RustConn"]' "${module}"
grep -qF "ExecStart = \"\${espanso}/bin/espanso launcher\"" "${module}"
test ! -e "${aspect_root}/apply.sh"
test ! -e "${aspect_root}/manifests"
