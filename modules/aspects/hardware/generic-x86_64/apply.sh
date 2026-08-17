#!/usr/bin/env bash
set -euo pipefail

build_root="${PURPLEFIN_BUILD_ROOT:-/tmp/purplefin-build}"
source "${build_root}/bootc/builder/lib/authselect-features.sh"
source "${build_root}/bootc/builder/lib/hardware-security.sh"
purplefin_apply_hardware_security generic-x86_64
