#!/usr/bin/env bash
set -euo pipefail

build_root="${FINITE_BUILD_ROOT:-/tmp/finite-build}"
generated_root="${FINITE_GENERATED_ROOT:?FINITE_GENERATED_ROOT is required}"
installer="${generated_root}/bootc/generated/determinate-nix-installer"
lock="${generated_root}/bootc/generated/determinate-nix.json"
policy="${generated_root}/bootc/generated/determinate-nix.pp"
file_contexts="${generated_root}/bootc/generated/nix.fc"
seed=/usr/lib/finite/determinate-nix-seed

test -x "${installer}"
test -s "${policy}"
test -s "${file_contexts}"
test -f "${lock}"
[[ "$(jq -er .architecture "${lock}")" == x86_64-linux ]]
minimum_runtime_version="$(jq -er .minimumRuntimeVersion "${lock}")"
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

# The native Fedora package intentionally establishes /nix, the build users,
# and the host package contract first. Determinate currently aborts its Linux
# planner when the package-provided nix-env is visible, even though this empty
# native bootstrap is safe to replace. Hide that one preflight probe for the
# duration of the pinned installer and restore the RPM-owned binary verbatim.
native_nix_env=/usr/bin/nix-env
hidden_native_nix_env=/usr/lib/finite/native-nix-env
test -x "${native_nix_env}"
install -d -m 0755 /usr/lib/finite
mv "${native_nix_env}" "${hidden_native_nix_env}"
restore_native_nix_env() {
	if [[ -e "${hidden_native_nix_env}" ]]; then
		mv "${hidden_native_nix_env}" "${native_nix_env}"
	fi
}
trap restore_native_nix_env EXIT
if command -v nix-env >/dev/null 2>&1; then
	echo 'Fedora native nix-env is still visible after preparing the Determinate handoff' >&2
	exit 1
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
restore_native_nix_env
trap - EXIT

test -x /usr/local/bin/determinate-nixd
install -D -m 0555 /usr/local/bin/determinate-nixd /usr/bin/determinate-nixd
rm -f /usr/local/bin/determinate-nixd
if [[ -L /usr/local ]]; then
	rmdir /var/usrlocal/bin
fi
install -D -m 0444 "${policy}" /usr/share/selinux/packages/determinate-nix.pp
install -D -m 0444 "${file_contexts}" /usr/share/finite/selinux/nix.fc
/usr/libexec/finite/require-determinate-nix-version \
	"${minimum_runtime_version}"

# The installer emits mutable-host unit overrides. Finite vendors the same
# unit contracts under /usr/lib/systemd/system and owns the bootc mount order.
rm -f \
	/etc/tmpfiles.d/nix-daemon.conf \
	/etc/tmpfiles.d/nix-filesystem.conf \
	/etc/systemd/system/determinate-nixd.socket \
	/etc/systemd/system/nix-daemon.service \
	/etc/systemd/system/nix-daemon.socket

# Finite provisions the complete persistent tree below /var/home/nix before
# bind-mounting it on /nix. The Fedora package tmpfiles entries run earlier
# against the immutable /nix placeholder and only produce read-only-filesystem
# errors. Override both vendor files with empty higher-priority /etc files.
# Regular files keep bootc's image-root lint from following /dev/null outside
# the container filesystem, as it would with systemd's usual symlink mask.
install -m 0644 /dev/null /etc/tmpfiles.d/nix-daemon.conf
install -m 0644 /dev/null /etc/tmpfiles.d/nix-filesystem.conf

# Determinate's systemd links target mutable-host overrides that Finite removes
# above. Delete the associated enablement links before installing Finite's
# immutable vendor units.
find /etc/systemd/system -type l \( \
	-lname '/etc/systemd/system/determinate-nixd.socket' -o \
	-lname '/etc/systemd/system/nix-daemon.service' -o \
	-lname '/etc/systemd/system/nix-daemon.socket' \
\) -delete

install -d -m 0755 /usr/lib/finite
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

# Assert that the Fedora package did not replace Finite's Determinate units,
# then activate them from the immutable vendor tree. This also repairs upgrades
# from hosts where the equivalent /etc enablement links were locally absent.
bash "${build_root}/modules/aspects/base/install-nix-systemd-units.sh"
