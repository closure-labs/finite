#!/usr/bin/env bash
set -euo pipefail

build_root="${PURPLEFIN_BUILD_ROOT:-/tmp/purplefin-build}"
# shellcheck source=/tmp/purplefin-build/lib/overlay.sh
source "${build_root}/lib/overlay.sh"

echo ":: Applying support devops component"
"${build_root}/components/devops/apply.sh"
purplefin_apply_role_overlay support

echo ":: Installing support role applications"
dnf5 -y --setopt=install_weak_deps=False install espanso-wayland
if command -v espanso >/dev/null 2>&1 && command -v setcap >/dev/null 2>&1; then
	setcap "cap_dac_override+p" "$(command -v espanso)"
fi
systemctl --global enable espanso.service
