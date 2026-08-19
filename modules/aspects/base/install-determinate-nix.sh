#!/usr/bin/env bash
set -euo pipefail

generated_root="${PURPLEFIN_GENERATED_ROOT:?PURPLEFIN_GENERATED_ROOT is required}"
installer="${generated_root}/bootc/generated/determinate-nix-installer"
lock="${generated_root}/bootc/generated/determinate-nix.json"
policy="${generated_root}/bootc/generated/determinate-nix.pp"
seed=/usr/lib/purplefin/determinate-nix-seed

test -x "${installer}"
test -s "${policy}"
test -f "${lock}"
[[ "$(jq -er .architecture "${lock}")" == x86_64-linux ]]
[[ ! -e "${seed}" ]]
[[ -d /nix ]]
[[ "$(rpm -qf --qf '%{NAME}\n' /nix)" == nix-filesystem ]]
[[ ! -e /nix/receipt.json ]]

# Bluefin follows the OSTree convention of linking /usr/local to
# /var/usrlocal. Materialize its target before the upstream installer creates
# /usr/local/bin/determinate-nixd.
if [[ -L /usr/local ]]; then
	[[ "$(readlink /usr/local)" == ../var/usrlocal ]]
	install -d -m 0755 /var/usrlocal/bin
fi

HOME=/var/roothome "${installer}" install linux \
	--determinate \
	--diagnostic-endpoint "" \
	--nix-build-group-id 30000 \
	--nix-build-user-count 10 \
	--nix-build-user-id-base 30000 \
	--nix-build-user-prefix nixbld- \
	--no-confirm \
	--no-modify-profile \
	--no-start-daemon

test -x /usr/local/bin/determinate-nixd
install -D -m 0555 /usr/local/bin/determinate-nixd /usr/bin/determinate-nixd
rm -f /usr/local/bin/determinate-nixd
if [[ -L /usr/local ]]; then
	rmdir /var/usrlocal/bin
fi
install -D -m 0444 "${policy}" /usr/share/selinux/packages/determinate-nix.pp

# The installer emits mutable-host unit overrides. Purplefin vendors the same
# unit contracts under /usr/lib/systemd/system and owns the bootc mount order.
rm -f \
	/etc/tmpfiles.d/nix-daemon.conf \
	/etc/systemd/system/determinate-nixd.socket \
	/etc/systemd/system/nix-daemon.service \
	/etc/systemd/system/nix-daemon.socket

# Determinate's tmpfiles entry is an absolute symlink into /nix. That is valid
# after the boot mount but escapes bootc's image root during lint. Fedora's
# nix-daemon package already vendors the equivalent native tmpfiles contract.
find /etc/systemd/system -type l \( \
	-lname '/etc/systemd/system/determinate-nixd.socket' -o \
	-lname '/etc/systemd/system/nix-daemon.service' -o \
	-lname '/etc/systemd/system/nix-daemon.socket' \
\) -delete

install -d -m 0755 /usr/lib/purplefin
install -d -m 0755 "${seed}"
shopt -s dotglob nullglob
nix_entries=(/nix/*)
((${#nix_entries[@]} > 0))
mv -- "${nix_entries[@]}" "${seed}/"
shopt -u dotglob nullglob

# Installer shell self-tests use root's OSTree home. Bluefin does not ship that
# directory, so discard the generated Fish state, profile links, and local
# diagnostics instead of baking transient build data into /var.
rm -rf /var/roothome

test -x "${seed}/nix-installer"
test -f "${seed}/receipt.json"
test -d "${seed}/store"
test -d "${seed}/var/nix"
systemctl enable nix-daemon.service nix-daemon.socket determinate-nixd.socket
