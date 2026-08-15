#!/usr/bin/env bash
set -euo pipefail

build_root="${PURPLEFIN_BUILD_ROOT:-/tmp/purplefin-build}"
# shellcheck source=/tmp/purplefin-build/lib/overlay.sh
source "${build_root}/lib/overlay.sh"
purplefin_apply_role_overlay it
