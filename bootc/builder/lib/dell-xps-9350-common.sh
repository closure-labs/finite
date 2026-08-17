#!/usr/bin/env bash
# Shared image-build wiring for Dell XPS 13 9350 non-camera policies.

purplefin_configure_dell_xps_9350_common() {
	local battery_service="purplefin-dell-xps-9350-battery.service"
	local panel_service="purplefin-dell-xps-9350-panel.service"
	local panel_wants="/etc/systemd/user/graphical-session.target.wants/${panel_service}"
	local lid_auth_helper="/usr/libexec/purplefin/dell-lid-is-open"
	local lid_auth_stack="/etc/pam.d/purplefin-dell-lid-auth"
	local password_auth_stack="/etc/pam.d/purplefin-dell-password-auth"
	local schema_dir="/usr/share/glib-2.0/schemas"
	local tuned_ppd_conf="/etc/tuned/ppd.conf"
	local tuned_profile="purplefin-dell-xps-9350-performance"
	local tuned_profile_conf="/usr/lib/tuned/profiles/${tuned_profile}/tuned.conf"
	local lid_validation_dir schema_validation_dir tuned_ppd_tmp command expected_setting

	for command in busctl gdctl gdbus gsettings glib-compile-schemas systemd-hwdb upower; do
		command -v "${command}" >/dev/null 2>&1 || {
			echo "Dell XPS 13 9350 policy requires ${command}" >&2
			exit 1
		}
	done
	test -f /usr/lib/systemd/system/upower.service

	chmod 0755 /usr/libexec/purplefin/configure-dell-xps-9350-battery
	chmod 0755 "${lid_auth_helper}"
	chmod 0755 /usr/libexec/purplefin/dell-xps-9350-panel-policy
	chmod 0644 \
		/etc/pam.d/polkit-1 \
		"${lid_auth_stack}" \
		"${password_auth_stack}" \
		/etc/pam.d/sudo

	echo ":: Configuring Dell XPS 9350 lid-aware privilege authentication"
	test -x "${lid_auth_helper}"
	grep -qxF 'auth       substack     purplefin-dell-lid-auth' /etc/pam.d/sudo
	grep -qxF 'auth       substack     purplefin-dell-lid-auth' /etc/pam.d/polkit-1
	grep -qxF 'auth [success=2 ignore=2 default=ignore] pam_exec.so quiet quiet_log /usr/bin/env -i /usr/libexec/purplefin/dell-lid-is-open' "${lid_auth_stack}"
	grep -qxF 'auth substack purplefin-dell-password-auth' "${lid_auth_stack}"
	grep -qxF 'auth substack system-auth' "${lid_auth_stack}"
	grep -qxF 'auth sufficient pam_unix.so' "${password_auth_stack}"
	! grep -Eq 'pam_(fprintd|u2f)[.]so' "${password_auth_stack}"
	lid_validation_dir="$(mktemp -d)"
	install -d "${lid_validation_dir}/LID0"
	printf '%s\n' 'state: open' >"${lid_validation_dir}/LID0/state"
	"${lid_auth_helper}" --state-root "${lid_validation_dir}"
	printf '%s\n' 'state: closed' >"${lid_validation_dir}/LID0/state"
	if "${lid_auth_helper}" --state-root "${lid_validation_dir}"; then
		echo "Dell lid helper accepted a closed test lid" >&2
		exit 1
	fi
	rm -rf "${lid_validation_dir}"

	echo ":: Configuring Dell XPS 9350 battery policy"
	systemd-hwdb --strict update
	systemd-hwdb query 'battery:BAT0:DELL TR7FC488:dmi:bvnDellInc.:svnDellInc.:pnXPS139350:' |
		grep -qx 'CHARGE_LIMIT=75,80'
	systemctl enable "${battery_service}"

	echo ":: Configuring Dell XPS 9350 laptop-safe Performance profile"
	test -f "${tuned_ppd_conf}"
	test -f "${tuned_profile_conf}"
	for expected_setting in \
		'include=balanced' \
		'energy_performance_preference=performance' \
		'boost=1' \
		'platform_profile=performance'; do
		grep -qxF "${expected_setting}" "${tuned_profile_conf}"
	done
	! grep -Eq '^[[:space:]]*(min_perf_pct|\[vm([^]]*)?\]|\[disk\])[[:space:]]*(=|$)' "${tuned_profile_conf}"
	tuned_ppd_tmp="$(mktemp)"
	awk -v profile="${tuned_profile}" '
		/^\[profiles\]$/ {
			in_profiles = 1
			print
			next
		}
		/^\[/ {
			in_profiles = 0
		}
		in_profiles && /^[[:space:]]*performance[[:space:]]*=/ {
			print "performance=" profile
			replaced = 1
			next
		}
		{ print }
		END { if (!replaced) exit 1 }
	' "${tuned_ppd_conf}" >"${tuned_ppd_tmp}"
	install -m 0644 "${tuned_ppd_tmp}" "${tuned_ppd_conf}"
	rm -f "${tuned_ppd_tmp}"
	grep -qx "performance=${tuned_profile}" "${tuned_ppd_conf}"

	echo ":: Configuring Dell XPS 9350 panel and ambient-brightness policy"
	test -L "${panel_wants}"
	test "$(readlink "${panel_wants}")" = '../../../../usr/lib/systemd/user/purplefin-dell-xps-9350-panel.service'
	schema_validation_dir="$(mktemp -d)"
	install -m 0644 "${schema_dir}/org.gnome.settings-daemon.enums.xml" "${schema_validation_dir}/"
	install -m 0644 "${schema_dir}/org.gnome.settings-daemon.plugins.power.gschema.xml" "${schema_validation_dir}/"
	install -m 0644 "${schema_dir}/zz9-purplefin-dell-xps-9350.gschema.override" "${schema_validation_dir}/"
	glib-compile-schemas --strict --dry-run "${schema_validation_dir}"
	rm -rf "${schema_validation_dir}"
	# The inherited Bluefin schema tree can contain stale Fedora override keys.
	# Compile it normally so those unrelated keys are ignored rather than fatal.
	glib-compile-schemas "${schema_dir}"
	GSETTINGS_SCHEMA_DIR="${schema_dir}" GSETTINGS_BACKEND=memory gsettings get \
		org.gnome.settings-daemon.plugins.power ambient-enabled | grep -qx true
}
