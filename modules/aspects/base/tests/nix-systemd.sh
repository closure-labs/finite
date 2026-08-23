#!/usr/bin/env bash
set -euo pipefail

aspect_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
unit_source="${aspect_root}/rootfs/usr/lib/systemd/system"
test_root="$(mktemp -d)"
trap 'rm -rf -- "${test_root}"' EXIT

install -d \
  "${test_root}/usr/bin" \
  "${test_root}/usr/lib/systemd/system" \
  "${test_root}/usr/libexec/finite"
for unit in \
  basic.target \
  local-fs.target \
  multi-user.target \
  shutdown.target \
  sockets.target \
  sysinit.target \
  system.slice; do
  printf '[Unit]\nDescription=Test stub for %s\n' "${unit}" > \
    "${test_root}/usr/lib/systemd/system/${unit}"
done
cp \
  "${unit_source}/finite-nix-selinux.service" \
  "${unit_source}/finite-nix-seed.service" \
  "${unit_source}/finite-nix-socket-cleanup.service" \
  "${unit_source}/nix.mount" \
  "${unit_source}/nix-daemon.service" \
  "${unit_source}/nix-daemon.socket" \
  "${unit_source}/determinate-nixd.socket" \
  "${test_root}/usr/lib/systemd/system/"

true_command="$(type -P true)"
install -m 0755 "${true_command}" \
  "${test_root}/usr/libexec/finite/install-determinate-nix-selinux-policy"
install -m 0755 "${true_command}" \
  "${test_root}/usr/libexec/finite/provision-determinate-nix"
install -m 0755 "${true_command}" "${test_root}/usr/bin/determinate-nixd"
install -m 0755 "$(type -P rm)" "${test_root}/usr/bin/rm"

FINITE_NIX_SYSTEMD_UNIT_ROOT="${test_root}/usr/lib/systemd/system" \
  bash "${aspect_root}/install-nix-systemd-units.sh"

test "$(readlink "${test_root}/usr/lib/systemd/system/multi-user.target.wants/nix-daemon.service")" = \
  ../nix-daemon.service
test "$(readlink "${test_root}/usr/lib/systemd/system/sockets.target.wants/nix-daemon.socket")" = \
  ../nix-daemon.socket
test "$(readlink "${test_root}/usr/lib/systemd/system/sockets.target.wants/determinate-nixd.socket")" = \
  ../determinate-nixd.socket

systemd-analyze \
  --root="${test_root}" \
  --man=no \
  --generators=no \
  verify \
  finite-nix-selinux.service \
  finite-nix-seed.service \
  finite-nix-socket-cleanup.service \
  nix.mount \
  nix-daemon.service \
  nix-daemon.socket \
  determinate-nixd.socket
