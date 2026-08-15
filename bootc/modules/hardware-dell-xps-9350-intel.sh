#!/usr/bin/env bash
set -euo pipefail

build_root="${PURPLEFIN_BUILD_ROOT:-/tmp/purplefin-build}"
"${build_root}/overlays/hardware/dell-xps-9350-intel/configure.sh"
source "${build_root}/lib/authselect-features.sh"
source "${build_root}/lib/hardware-security.sh"
purplefin_apply_hardware_security dell-xps-9350-intel
