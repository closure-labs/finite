#!/usr/bin/env bash
set -euo pipefail

namespace="${1:?usage: architecture.sh ARCHITECTURE_ROOT}/namespace.mmd"
grep -qF 'profiles_dale --> features_roles_support' "${namespace}"
grep -qF 'operations_github_build --> operations_checks_all' "${namespace}"
grep -qF 'operations_checks_all --> operations_checks_repository_contracts' "${namespace}"
grep -qF 'operations_checks_all --> operations_checks_bootc_engine' "${namespace}"
grep -qF 'operations_github_build --> operations_delivery_installer' "${namespace}"
grep -qF 'operations_updates_bluefin --> sources_bluefin' "${namespace}"
grep -qF 'operations_github_bluefin_update --> operations_updates_bluefin' "${namespace}"
grep -qF 'operations_updates_determinate_nix --> sources_determinate_nix' "${namespace}"
grep -qF 'operations_github_determinate_nix_update --> operations_updates_determinate_nix' \
  "${namespace}"
