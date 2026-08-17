#!/usr/bin/env bash
set -euo pipefail

aspect_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
unit="${aspect_root}/rootfs/usr/lib/systemd/user/espanso.service"

test -x "${aspect_root}/apply.sh"
test -f "${unit}"
grep -qxF 'After=graphical-session.target' "${unit}"
grep -qxF 'PartOf=graphical-session.target' "${unit}"
grep -qxF 'ExecStart=/usr/bin/espanso launcher' "${unit}"
grep -qxF 'WantedBy=graphical-session.target' "${unit}"
grep -qF '[Flatpak Preinstall io.github.totoshko88.RustConn]' \
	"${aspect_root}/manifests/flatpaks.preinstall"
