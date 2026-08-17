#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
profile_root="${repo_root}/bootc/overlays/hardware/dell-xps-9350-intel/files"
helper="${profile_root}/usr/libexec/purplefin/dell-lid-is-open"
lid_auth="${profile_root}/etc/pam.d/purplefin-dell-lid-auth"
password_auth="${profile_root}/etc/pam.d/purplefin-dell-password-auth"
sudo_auth="${profile_root}/etc/pam.d/sudo"
polkit_auth="${profile_root}/etc/pam.d/polkit-1"
tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

fail() {
	printf 'dell-lid-auth: %s\n' "$*" >&2
	exit 1
}

expect_closed() {
	if env -i "${BASH}" "${helper}" --state-root "$1"; then
		fail "accepted non-open lid state under $1"
	fi
}

test -x "${helper}"
bash -n "${helper}"

lid_root="${tmpdir}/lid"
install -d "${lid_root}"
expect_closed "${lid_root}"

install -d "${lid_root}/LID0"
printf '%s\n' 'state: open' >"${lid_root}/LID0/state"
env -i "${BASH}" "${helper}" --state-root "${lid_root}"

printf '%s\n' "#!${BASH}" 'printf '\''%s\n'\'' '\''b false'\''' >"${tmpdir}/busctl-open"
printf '%s\n' "#!${BASH}" 'printf '\''%s\n'\'' '\''b true'\''' >"${tmpdir}/busctl-closed"
printf '%s\n' "#!${BASH}" 'printf '\''%s\n'\'' '\''unexpected'\''' >"${tmpdir}/busctl-malformed"
printf '%s\n' "#!${BASH}" 'exit 1' >"${tmpdir}/busctl-fail"
chmod 0755 "${tmpdir}"/busctl-*

# Either source reporting closed wins over an open result from the other.
printf '%s\n' 'state: closed' >"${lid_root}/LID0/state"
if env -i "${BASH}" "${helper}" --test-sources "${tmpdir}/busctl-open" "${lid_root}"; then
	fail 'accepted ACPI/logind disagreement with ACPI closed'
fi
printf '%s\n' 'state: open' >"${lid_root}/LID0/state"
if env -i "${BASH}" "${helper}" --test-sources "${tmpdir}/busctl-closed" "${lid_root}"; then
	fail 'accepted logind closed state'
fi

printf '%s\n' 'state: open' >"${lid_root}/LID0/state"
env -i "${BASH}" "${helper}" --test-sources "${tmpdir}/busctl-open" "${lid_root}"

# Malformed or unavailable logind data falls back to the ACPI state.
env -i "${BASH}" "${helper}" --test-sources "${tmpdir}/busctl-malformed" "${lid_root}"
env -i "${BASH}" "${helper}" --test-sources "${tmpdir}/busctl-fail" "${lid_root}"

# A known-open logind state remains usable on systems without an ACPI file.
empty_lid_root="${tmpdir}/no-acpi-lid"
install -d "${empty_lid_root}"
env -i "${BASH}" "${helper}" --test-sources "${tmpdir}/busctl-open" "${empty_lid_root}"
if env -i "${BASH}" "${helper}" --test-sources "${tmpdir}/busctl-malformed" "${empty_lid_root}"; then
	fail 'accepted indeterminate lid state without an ACPI fallback'
fi

printf '%s\n' 'state: closed' >"${lid_root}/LID0/state"
expect_closed "${lid_root}"

printf '%s\n' 'state: unknown' >"${lid_root}/LID0/state"
expect_closed "${lid_root}"

printf '%s\n' 'malformed' >"${lid_root}/LID0/state"
expect_closed "${lid_root}"

printf '%s\n' 'state: open extra' >"${lid_root}/LID0/state"
expect_closed "${lid_root}"

printf '%s\n' 'state: open' >"${lid_root}/LID0/state"
install -d "${lid_root}/LID1"
printf '%s\n' 'state: open' >"${lid_root}/LID1/state"
env -i "${BASH}" "${helper}" --state-root "${lid_root}"

printf '%s\n' 'state: closed' >"${lid_root}/LID1/state"
expect_closed "${lid_root}"

if bash "${helper}" --invalid-option "${lid_root}"; then
	fail 'accepted an unsupported test option'
fi

grep -qxF 'auth [success=2 ignore=2 default=ignore] pam_exec.so quiet quiet_log /usr/bin/env -i /usr/libexec/purplefin/dell-lid-is-open' "${lid_auth}"
grep -qxF 'auth substack purplefin-dell-password-auth' "${lid_auth}"
grep -qxF 'auth [success=1 default=die] pam_permit.so' "${lid_auth}"
grep -qxF 'auth substack system-auth' "${lid_auth}"
test "$(grep -c '^auth ' "${lid_auth}")" -eq 4

grep -qxF 'auth required pam_env.so' "${password_auth}"
grep -qxF 'auth required pam_faildelay.so delay=2000000' "${password_auth}"
grep -qxF 'auth sufficient pam_unix.so' "${password_auth}"
grep -qxF 'auth required pam_deny.so' "${password_auth}"
if grep -Eq 'pam_(fprintd|u2f)[.]so|nullok' "${password_auth}"; then
	exit 1
fi

grep -qxF 'auth       substack     purplefin-dell-lid-auth' "${sudo_auth}"
grep -qxF 'account    include      system-auth' "${sudo_auth}"
grep -qxF 'password   include      system-auth' "${sudo_auth}"
grep -qxF 'session    include      system-auth' "${sudo_auth}"

grep -qxF 'auth       substack     purplefin-dell-lid-auth' "${polkit_auth}"
grep -qxF 'account    include      system-auth' "${polkit_auth}"
grep -qxF 'password   include      system-auth' "${polkit_auth}"
grep -qxF 'session    include      system-auth' "${polkit_auth}"

test ! -e "${profile_root}/etc/pam.d/systemd-run0"
