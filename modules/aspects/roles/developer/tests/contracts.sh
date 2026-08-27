#!/usr/bin/env bash
set -euo pipefail

aspect_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
module="templates/home-manager/modules/aspects/roles/developer/home.nix"

# shellcheck disable=SC2016 # Match the literal Nix interpolation.
grep -qF 'inputs.devenv.packages.${pkgs.stdenv.hostPlatform.system}.devenv' "${module}"
grep -qF 'home.sessionVariables.FINITE_ROLE_DEVELOPER = "1"' "${module}"
test ! -e "${aspect_root}/apply.sh"
test ! -e "${aspect_root}/manifests"
