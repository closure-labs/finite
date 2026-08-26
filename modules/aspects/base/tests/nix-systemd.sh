#!/usr/bin/env bash
set -euo pipefail

# Keep offline verification independent of the host/userdb manager.
export SYSTEMD_BYPASS_USERDB=1

aspect_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
unit_source="${aspect_root}/rootfs/usr/lib/systemd/system"
test_root="$(mktemp -d)"
trap 'rm -rf -- "${test_root}"' EXIT

install -d \
  "${test_root}/usr/bin" \
  "${test_root}/usr/lib/systemd/system" \
  "${test_root}/usr/libexec/finite"
printf '%s\n' \
  '[Unit]' \
  'Description=Test stub for basic.target' \
  'Requires=sysinit.target' \
  'Wants=sockets.target' \
  'After=sysinit.target sockets.target' > \
  "${test_root}/usr/lib/systemd/system/basic.target"
printf '%s\n' \
  '[Unit]' \
  'Description=Test stub for sysinit.target' \
  'Wants=local-fs.target' \
  'After=local-fs.target' > \
  "${test_root}/usr/lib/systemd/system/sysinit.target"
for unit in \
  local-fs.target \
  multi-user.target \
  shutdown.target \
  sockets.target \
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

# Reproduce the activation layout inherited from Fedora/Determinate. The
# Finite helper must remove these early/direct links, not merely add its later
# socket links alongside them.
install -d \
  "${test_root}/usr/lib/systemd/system/sockets.target.wants" \
  "${test_root}/usr/lib/systemd/system/multi-user.target.wants"
ln -s ../nix-daemon.socket \
  "${test_root}/usr/lib/systemd/system/sockets.target.wants/nix-daemon.socket"
ln -s ../determinate-nixd.socket \
  "${test_root}/usr/lib/systemd/system/sockets.target.wants/determinate-nixd.socket"
ln -s ../nix-daemon.service \
  "${test_root}/usr/lib/systemd/system/multi-user.target.wants/nix-daemon.service"

FINITE_NIX_SYSTEMD_UNIT_ROOT="${test_root}/usr/lib/systemd/system" \
  bash "${aspect_root}/install-nix-systemd-units.sh"

test ! -L \
  "${test_root}/usr/lib/systemd/system/sockets.target.wants/nix-daemon.socket"
test ! -L \
  "${test_root}/usr/lib/systemd/system/sockets.target.wants/determinate-nixd.socket"
test ! -L \
  "${test_root}/usr/lib/systemd/system/multi-user.target.wants/nix-daemon.service"
test "$(readlink "${test_root}/usr/lib/systemd/system/multi-user.target.wants/nix-daemon.socket")" = \
  ../nix-daemon.socket
test "$(readlink "${test_root}/usr/lib/systemd/system/multi-user.target.wants/determinate-nixd.socket")" = \
  ../determinate-nixd.socket

grep -qFx 'DefaultDependencies=no' \
  "${test_root}/usr/lib/systemd/system/nix-daemon.socket"
grep -qFx 'After=basic.target finite-nix-socket-cleanup.service' \
  "${test_root}/usr/lib/systemd/system/nix-daemon.socket"
grep -qFx 'Before=nix-daemon.service multi-user.target shutdown.target' \
  "${test_root}/usr/lib/systemd/system/nix-daemon.socket"
grep -qFx 'Conflicts=shutdown.target' \
  "${test_root}/usr/lib/systemd/system/nix-daemon.socket"
grep -qFx 'DefaultDependencies=no' \
  "${test_root}/usr/lib/systemd/system/determinate-nixd.socket"
grep -qFx 'Requires=nix-daemon.socket determinate-nixd.socket' \
  "${test_root}/usr/lib/systemd/system/nix-daemon.service"
grep -qFx 'After=nix-daemon.socket determinate-nixd.socket' \
  "${test_root}/usr/lib/systemd/system/nix-daemon.service"

# verify validates unit syntax and references. Test mode additionally resolves
# the initial boot transaction, which is where ordering cycles are detected.
# Pure Nix builders intentionally have no /run/systemd, which these systemd
# offline tools require; the explicit ordering contracts above still run there.
if [[ -d /run/systemd ]]; then
  systemd-analyze \
    --root="${test_root}" \
    --man=no \
    --generators=no \
    verify \
    multi-user.target \
    finite-nix-selinux.service \
    finite-nix-seed.service \
    finite-nix-socket-cleanup.service \
    nix.mount \
    nix-daemon.service \
    nix-daemon.socket \
    determinate-nixd.socket

  transaction_log="$({
    systemd_analyze="$(type -P systemd-analyze)"
    systemd_binary="${FINITE_SYSTEMD_BINARY:-${systemd_analyze%/bin/systemd-analyze}/lib/systemd/systemd}"
    test -x "${systemd_binary}"
    SYSTEMD_UNIT_PATH="${test_root}/usr/lib/systemd/system" \
      "${systemd_binary}" \
        --test \
        --system \
        --unit=multi-user.target \
        --log-level=warning \
        --log-target=console
  } 2>&1)"
  if grep -qi 'ordering cycle' <<<"${transaction_log}"; then
    printf '%s\n' "${transaction_log}" >&2
    exit 1
  fi
fi
