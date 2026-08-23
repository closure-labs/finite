#!/usr/bin/env bash
set -euo pipefail

build_root="${FINITE_BUILD_ROOT:-/tmp/finite-build}"
source "${build_root}/bootc/builder/lib/authselect-features.sh"
source "${build_root}/bootc/builder/lib/hardware-security.sh"
finite_apply_hardware_security generic-x86_64
