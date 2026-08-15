#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
battery_helper="${repo_root}/bootc/overlays/hardware/dell-xps-9350-intel/files/usr/libexec/purplefin/configure-dell-xps-9350-battery"
panel_helper="${repo_root}/bootc/overlays/hardware/dell-xps-9350-intel/files/usr/libexec/purplefin/dell-xps-9350-panel-policy"
vendor_battery_config="${repo_root}/bootc/overlays/hardware/dell-xps-9350-intel/files/usr/lib/purplefin/dell-xps-9350-battery.conf"
tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

fail() {
	printf 'dell-xps-9350-policies: %s\n' "$*" >&2
	exit 1
}

install -d \
	"${tmpdir}/bin" \
	"${tmpdir}/battery/dmi" \
	"${tmpdir}/battery/power/BAT0" \
	"${tmpdir}/panel/dmi" \
	"${tmpdir}/panel/drm/card0-eDP-1" \
	"${tmpdir}/panel/power/AC" \
	"${tmpdir}/panel/state"

cat >"${tmpdir}/bin/upower" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == "--enumerate" ]]
printf '%s\n' /org/freedesktop/UPower/devices/battery_BAT0
EOF

cat >"${tmpdir}/bin/busctl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case " $* " in
	*" introspect "*)
		case "${MOCK_UPOWER_API:-present}" in
			present)
				printf '%s\n' EnableChargeThreshold ChargeThresholdSupported ChargeThresholdEnabled
				;;
			absent) printf '%s\n' Refresh ;;
			error) exit 1 ;;
		esac
		;;
	*" get-property "*" ChargeThresholdSupported ") printf '%s\n' 'b true' ;;
	*" get-property "*" ChargeThresholdEnabled ") printf '%s\n' 'b true' ;;
	*" call "*" EnableChargeThreshold b true ")
		printf '%s\n' EnableChargeThreshold >>"${MOCK_UPOWER_LOG}"
		;;
	*)
		printf 'unexpected busctl invocation: %s\n' "$*" >&2
		exit 1
		;;
esac
EOF

cat >"${tmpdir}/bin/gdbus" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${MOCK_ON_BATTERY:-false}" == true ]]; then
	printf '%s\n' '(<true>,)'
else
	printf '%s\n' '(<false>,)'
fi
EOF

cat >"${tmpdir}/bin/gdctl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
	show) cat "${MOCK_GDCTL_STATE}" ;;
	set) printf '%s\n' "$*" >>"${MOCK_GDCTL_LOG}" ;;
	*) exit 2 ;;
esac
EOF

cat >"${tmpdir}/bin/gsettings" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
	writable) printf '%s\n' true ;;
	set) printf '%s\n' "$*" >>"${MOCK_GSETTINGS_LOG}" ;;
	*) exit 2 ;;
esac
EOF

chmod 0755 "${tmpdir}/bin/"*

printf '%s\n' 'Dell Inc.' >"${tmpdir}/battery/dmi/sys_vendor"
printf '%s\n' 'XPS 13 9350' >"${tmpdir}/battery/dmi/product_name"
printf '%s\n' Battery >"${tmpdir}/battery/power/BAT0/type"
printf '%s\n' 'Trickle [Fast] Standard Adaptive Custom' >"${tmpdir}/battery/power/BAT0/charge_types"
printf '%s\n' 50 >"${tmpdir}/battery/power/BAT0/charge_control_start_threshold"
printf '%s\n' 90 >"${tmpdir}/battery/power/BAT0/charge_control_end_threshold"
: >"${tmpdir}/battery/upower.log"

battery_env=(
	"PURPLEFIN_DELL_BATTERY_VENDOR_CONFIG=${vendor_battery_config}"
	"PURPLEFIN_DELL_BATTERY_CONFIG=${tmpdir}/battery/local.conf"
	"PURPLEFIN_DELL_BATTERY_DMI_ROOT=${tmpdir}/battery/dmi"
	"PURPLEFIN_DELL_BATTERY_POWER_SUPPLY_ROOT=${tmpdir}/battery/power"
	"PURPLEFIN_DELL_BATTERY_BUSCTL=${tmpdir}/bin/busctl"
	"PURPLEFIN_DELL_BATTERY_UPOWER=${tmpdir}/bin/upower"
	"MOCK_UPOWER_LOG=${tmpdir}/battery/upower.log"
)

env "${battery_env[@]}" "${battery_helper}" >/dev/null
grep -qx EnableChargeThreshold "${tmpdir}/battery/upower.log"
grep -qx Custom "${tmpdir}/battery/power/BAT0/charge_types"
grep -qx 75 "${tmpdir}/battery/power/BAT0/charge_control_start_threshold"
grep -qx 80 "${tmpdir}/battery/power/BAT0/charge_control_end_threshold"

printf '%s\n' START_THRESHOLD=60 END_THRESHOLD=70 >"${tmpdir}/battery/local.conf"
printf '%s\n' 'Trickle [Custom] Fast Standard Adaptive' >"${tmpdir}/battery/power/BAT0/charge_types"
env "${battery_env[@]}" "${battery_helper}" >/dev/null
grep -qx 60 "${tmpdir}/battery/power/BAT0/charge_control_start_threshold"
grep -qx 70 "${tmpdir}/battery/power/BAT0/charge_control_end_threshold"

printf '%s\n' ENABLED=false >"${tmpdir}/battery/local.conf"
printf '%s\n' 41 >"${tmpdir}/battery/power/BAT0/charge_control_start_threshold"
env "${battery_env[@]}" "${battery_helper}" >/dev/null
grep -qx 41 "${tmpdir}/battery/power/BAT0/charge_control_start_threshold"

rm -f "${tmpdir}/battery/local.conf"
printf '%s\n' 'Trickle [Fast] Standard Adaptive Custom' >"${tmpdir}/battery/power/BAT0/charge_types"
MOCK_UPOWER_API=absent env "${battery_env[@]}" "${battery_helper}" >/dev/null
grep -qx 75 "${tmpdir}/battery/power/BAT0/charge_control_start_threshold"
if MOCK_UPOWER_API=error env "${battery_env[@]}" "${battery_helper}" >/dev/null 2>&1; then
	fail 'battery helper accepted a UPower transport failure'
fi

write_panel_state() {
	local current_mode="$1"
	local other_mode="$2"
	cat >"${tmpdir}/panel/gdctl-state" <<EOF
Monitors:
└──Monitor eDP-1 (Built-in display)
   ├──Modes (2)
   │   ├──${current_mode}
   │   │   └──Properties: (1)
   │   │       └──is-current ⇒  yes
   │   └──${other_mode}
Logical monitors:
└──Logical monitor #1
   ├──Position: (0, 0)
   ├──Scale: 1.25
   ├──Transform: normal
   └──Primary: yes
EOF
}

printf '%s\n' 'Dell Inc.' >"${tmpdir}/panel/dmi/sys_vendor"
printf '%s\n' 'XPS 13 9350' >"${tmpdir}/panel/dmi/product_name"
printf '%s\n' connected >"${tmpdir}/panel/drm/card0-eDP-1/status"
printf '%s\n' Mains >"${tmpdir}/panel/power/AC/type"
printf '%s\n' 1 >"${tmpdir}/panel/power/AC/online"
: >"${tmpdir}/panel/gdctl.log"
: >"${tmpdir}/panel/gsettings.log"

panel_env=(
	"HOME=${tmpdir}/panel/home"
	"XDG_CONFIG_HOME=${tmpdir}/panel/config"
	"XDG_STATE_HOME=${tmpdir}/panel/state"
	"PURPLEFIN_PANEL_DMI_ROOT=${tmpdir}/panel/dmi"
	"PURPLEFIN_PANEL_DRM_ROOT=${tmpdir}/panel/drm"
	"PURPLEFIN_PANEL_POWER_SUPPLY_ROOT=${tmpdir}/panel/power"
	"PURPLEFIN_PANEL_GDCTL=${tmpdir}/bin/gdctl"
	"PURPLEFIN_PANEL_GDBUS=${tmpdir}/bin/gdbus"
	"PURPLEFIN_PANEL_GSETTINGS=${tmpdir}/bin/gsettings"
	"MOCK_GDCTL_STATE=${tmpdir}/panel/gdctl-state"
	"MOCK_GDCTL_LOG=${tmpdir}/panel/gdctl.log"
	"MOCK_GSETTINGS_LOG=${tmpdir}/panel/gsettings.log"
)

write_panel_state 1920x1200@60.000 1920x1200@120.000+vrr
env "${panel_env[@]}" PURPLEFIN_PANEL_AMBIENT_BRIGHTNESS_MIGRATION_ENABLED=false \
	MOCK_ON_BATTERY=false "${panel_helper}" --apply >/dev/null
grep -qF -- '--scale 1.25 --transform normal --x 0 --y 0 --monitor eDP-1 --mode 1920x1200@120.000+vrr' \
	"${tmpdir}/panel/gdctl.log"

: >"${tmpdir}/panel/gdctl.log"
write_panel_state 1920x1200@120.000+vrr 1920x1200@60.000
env "${panel_env[@]}" PURPLEFIN_PANEL_AMBIENT_BRIGHTNESS_MIGRATION_ENABLED=false \
	MOCK_ON_BATTERY=true "${panel_helper}" --apply >/dev/null
grep -qF -- '--mode 1920x1200@60.000' "${tmpdir}/panel/gdctl.log"

install -d "${tmpdir}/panel/drm/card0-DP-1"
printf '%s\n' connected >"${tmpdir}/panel/drm/card0-DP-1/status"
: >"${tmpdir}/panel/gdctl.log"
env "${panel_env[@]}" PURPLEFIN_PANEL_AMBIENT_BRIGHTNESS_MIGRATION_ENABLED=false \
	MOCK_ON_BATTERY=false "${panel_helper}" --apply >/dev/null 2>&1 || true
test ! -s "${tmpdir}/panel/gdctl.log"
rm -rf "${tmpdir}/panel/drm/card0-DP-1"

write_panel_state 1920x1200@120.000+vrr 1920x1200@60.000
for _ in 1 2; do
	env "${panel_env[@]}" MOCK_ON_BATTERY=false "${panel_helper}" --apply >/dev/null
done
test "$(grep -cF 'set org.gnome.settings-daemon.plugins.power ambient-enabled true' "${tmpdir}/panel/gsettings.log")" -eq 1
test -f "${tmpdir}/panel/state/purplefin/dell-xps-9350-ambient-brightness-v1"
