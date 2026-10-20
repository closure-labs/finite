#!/usr/bin/env bash
# Privileged, disposable SELinux test; never restart or relabel the real GDM tree.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

if (( EUID != 0 )); then
	printf '%s\n' 'Administrator privileges required for the isolated SELinux fixture.' >&2
	exit 77
fi
[[ $(/usr/sbin/getenforce) == Enforcing ]] || {
	printf '%s\n' 'Enforcing SELinux is required; refusing a no-op labeling test.' >&2
	exit 77
}
if (( $# > 1 )); then
	printf '%s\n' 'Usage: gdm-selinux-migration.sh [tmpfiles-rule]' >&2
	exit 2
fi
if (( $# == 1 )); then
	# VM acceptance streams this script and tests the candidate's installed rule.
	rule=$1
else
	repository=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
	rule="$repository/files/system/usr/lib/tmpfiles.d/finite-gdm.conf"
fi
[[ -d /var/lib/gdm && ! -L /var/lib/gdm ]] || {
	printf '%s\n' 'Expected a real /var/lib/gdm directory as the mount target.' >&2
	exit 1
}
fixture=$(/usr/bin/mktemp -d /tmp/finite-gdm-selinux.XXXXXXXX)
trap '/usr/bin/rm -rf -- "$fixture"' EXIT
/usr/bin/mkdir "$fixture/tree"
/usr/bin/cp -- "$rule" "$fixture/rule.conf"
# Invoke exactly the reviewed rule, excluding comments and blank lines.
[[ $(/usr/bin/sed '/^[[:space:]]*#/d; /^[[:space:]]*$/d' "$fixture/rule.conf") == 'Z /var/lib/gdm - - - - -' ]] || {
	printf '%s\n' 'Unexpected GDM tmpfiles configuration; refusing privileged execution.' >&2
	exit 1
}
parent_namespace=$(/usr/bin/readlink /proc/self/ns/mnt)
real_gdm_inode=$(/usr/bin/stat -c '%d:%i' /var/lib/gdm)
# No user/PID namespace or chroot: use the actual enforcing policy and native tools.
# All /var/lib/gdm writes below resolve to the fixture in this private namespace.
/usr/bin/unshare --mount --propagation private /usr/bin/bash -s -- \
	"$fixture" "$parent_namespace" "$real_gdm_inode" <<'ISOLATED'
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
fixture=$1
[[ $(/usr/bin/readlink /proc/self/ns/mnt) != "$2" ]]
[[ $(/usr/sbin/getenforce) == Enforcing ]]
/usr/bin/mount --bind "$fixture/tree" /var/lib/gdm
[[ $(/usr/bin/findmnt -n --mountpoint /var/lib/gdm -o TARGET) == /var/lib/gdm ]]
[[ $(/usr/bin/stat -c '%d:%i' /var/lib/gdm) == "$(/usr/bin/stat -c '%d:%i' "$fixture/tree")" ]]
[[ $(/usr/bin/stat -c '%d:%i' /var/lib/gdm) != "$3" ]]
cd /var/lib/gdm
/usr/bin/mkdir -p seat0/config/zsh seat0/state .config/zsh .local/state
printf '%s\n' 'existing seat configuration' > seat0/config/zsh/.zshenv
printf '%s\n' 'legacy configuration to migrate' > .config/zsh/.zshrc
printf '%s\n' 'legacy persistent state' > .local/state/migration-test
/usr/bin/chmod 0750 seat0/config/zsh .config/zsh
/usr/bin/chmod 0640 seat0/config/zsh/.zshenv .config/zsh/.zshrc
/usr/bin/chmod 0600 .local/state/migration-test
/usr/bin/chown -R 60577:65534 seat0
/usr/bin/chcon -R -t usr_t /var/lib/gdm

metadata() { /usr/bin/find . -printf '%p %m %U %G\n' | /usr/bin/sort; }
labels() {
	local expected=${1:-xdm_var_lib_t}
	while IFS= read -r -d '' path; do
		context=$(/usr/bin/stat -c %C -- "$path")
		[[ $context == *:object_r:"$expected":* ]] || {
			printf 'Unexpected fixture label: %s %s\n' "$path" "$context" >&2
			return 1
		}
	done < <(/usr/bin/find . -print0)
}
labels usr_t
metadata > "$fixture/before"
# Explicit config argument: no other host tmpfiles rules are executed.
/usr/bin/systemd-tmpfiles --create "$fixture/rule.conf"
labels
metadata > "$fixture/after"
/usr/bin/cmp "$fixture/before" "$fixture/after"
/usr/bin/systemd-tmpfiles --create "$fixture/rule.conf"
labels
metadata > "$fixture/repeated"
/usr/bin/cmp "$fixture/before" "$fixture/repeated"
printf '%s\n' 'PASS: existing and legacy labels corrected; ownership/modes unchanged; repeat is stable.'

# Model GDM metadata-preserving migration after boot-time prelabeling.
/usr/bin/cp -a .config/. seat0/config/
/usr/bin/cp -a .local/state/. seat0/state/
/usr/bin/cmp .config/zsh/.zshrc seat0/config/zsh/.zshrc
/usr/bin/cmp .local/state/migration-test seat0/state/migration-test
[[ $(/usr/bin/stat -c '%a:%u:%g' .config/zsh/.zshrc) == "$(/usr/bin/stat -c '%a:%u:%g' seat0/config/zsh/.zshrc)" ]]
[[ $(/usr/bin/stat -c '%a:%u:%g' .local/state/migration-test) == "$(/usr/bin/stat -c '%a:%u:%g' seat0/state/migration-test)" ]]
labels
/usr/bin/find seat0 -printf '%p %m\n' | /usr/bin/sort > "$fixture/modes-before"
/usr/bin/chown -R 60578:65534 seat0/config seat0/state
while IFS= read -r -d '' path; do
	[[ $(/usr/bin/stat -c '%u:%g' -- "$path") == 60578:65534 ]]
done < <(/usr/bin/find seat0/config seat0/state -print0)
/usr/bin/find seat0 -printf '%p %m\n' | /usr/bin/sort > "$fixture/modes-after"
/usr/bin/cmp "$fixture/modes-before" "$fixture/modes-after"
labels
printf '%s\n' 'PASS: copy after prelabeling and numeric ownership reassignment retain correct labels/modes.'
ISOLATED
[[ $(/usr/bin/stat -c '%d:%i' /var/lib/gdm) == "$real_gdm_inode" ]]
printf '%s\n' 'PASS: isolated GDM SELinux migration fixture; production mount unchanged.'
