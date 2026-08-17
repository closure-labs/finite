#!/usr/bin/env bash
set -euo pipefail

# Intentional scaffold: do not ship unvalidated Framework-specific tuning.
build_root="${PURPLEFIN_BUILD_ROOT:-/tmp/purplefin-build}"
source "${build_root}/bootc/builder/lib/authselect-features.sh"
source "${build_root}/bootc/builder/lib/hardware-security.sh"
purplefin_apply_hardware_security framework-laptop
