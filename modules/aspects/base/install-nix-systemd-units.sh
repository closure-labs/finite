#!/usr/bin/env bash
set -euo pipefail

unit_root="${FINITE_NIX_SYSTEMD_UNIT_ROOT:-/usr/lib/systemd/system}"

grep -qFx \
	'ExecStart=@/usr/bin/determinate-nixd determinate-nixd daemon' \
	"${unit_root}/nix-daemon.service"
grep -qFx \
	'What=/var/home/nix' \
	"${unit_root}/nix.mount"

install_vendor_want() {
	local target="$1"
	local wants_dir="$2"
	local link="${unit_root}/${wants_dir}/${target}"

	if [[ -e "${link}" && ! -L "${link}" ]]; then
		echo "Refusing to replace non-symlink systemd activation path: ${link}" >&2
		exit 1
	fi

	install -d -m 0755 "${unit_root}/${wants_dir}"
	ln -sfn "../${target}" "${link}"
}

remove_vendor_want() {
	local target="$1"
	local wants_dir="$2"
	local link="${unit_root}/${wants_dir}/${target}"

	if [[ -e "${link}" && ! -L "${link}" ]]; then
		echo "Refusing to remove non-symlink systemd activation path: ${link}" >&2
		exit 1
	fi

	rm -f -- "${link}"
}

# Store activation in the immutable vendor tree. Fresh installations therefore
# start Nix without depending on an /etc merge, while bootc upgrades repair
# hosts whose previous local /etc state omitted the enablement links.
# Fedora and the Determinate installer enable these sockets from
# sockets.target. That target is ordered before basic.target, but Finite must
# first install the SELinux policy, seed /var/home/nix, and mount it at /nix.
# Remove the inherited early-boot links so they cannot reintroduce that cycle.
# Keep the daemon socket-activated instead of also starting it directly.
remove_vendor_want nix-daemon.socket sockets.target.wants
remove_vendor_want determinate-nixd.socket sockets.target.wants
remove_vendor_want nix-daemon.service multi-user.target.wants
install_vendor_want nix-daemon.socket multi-user.target.wants
install_vendor_want determinate-nixd.socket multi-user.target.wants
