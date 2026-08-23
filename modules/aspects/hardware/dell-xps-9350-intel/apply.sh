#!/usr/bin/env bash
set -euo pipefail

build_root="${FINITE_BUILD_ROOT:-/tmp/finite-build}"
"${build_root}/modules/aspects/hardware/dell-xps-9350-intel/configure.sh"
source "${build_root}/bootc/builder/lib/authselect-features.sh"
source "${build_root}/bootc/builder/lib/hardware-security.sh"
finite_apply_hardware_security dell-xps-9350-intel
