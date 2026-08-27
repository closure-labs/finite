#!/usr/bin/env bash
set -euo pipefail

panel_helper="templates/home-manager/modules/aspects/hardware/dell-xps-9350-intel/dell-xps-9350-panel-policy"
panel_config="templates/home-manager/modules/aspects/hardware/dell-xps-9350-intel/rootfs/usr/share/finite/dell-xps-9350-panel.conf"
test_root="$(mktemp -d)"
trap 'rm -rf -- "${test_root}"' EXIT

fail() {
	printf 'dell-panel-policy: %s\n' "$*" >&2
	exit 1
}

install -d \
	"${test_root}/bin" \
	"${test_root}/dmi" \
	"${test_root}/drm/card0-eDP-1" \
	"${test_root}/power/AC" \
	"${test_root}/state"

cat >"${test_root}/bin/gdbus" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${MOCK_ON_BATTERY:-false}" == true ]]; then
	printf '%s\n' '(<true>,)'
else
	printf '%s\n' '(<false>,)'
fi
EOF

cat >"${test_root}/bin/gdctl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
	show) cat "${MOCK_GDCTL_STATE}" ;;
	set) printf '%s\n' "$*" >>"${MOCK_GDCTL_LOG}" ;;
	*) exit 2 ;;
esac
EOF

cat >"${test_root}/bin/gsettings" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
	writable) printf '%s\n' true ;;
	set) printf '%s\n' "$*" >>"${MOCK_GSETTINGS_LOG}" ;;
	*) exit 2 ;;
esac
EOF

for mock in "${test_root}/bin/"*; do
	sed -i "1c #!${BASH}" "${mock}"
done
chmod 0755 "${test_root}/bin/"*

write_panel_state() {
	local current_mode="$1"
	local other_mode="$2"
	cat >"${test_root}/gdctl-state" <<EOF
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

printf '%s\n' 'Dell Inc.' >"${test_root}/dmi/sys_vendor"
printf '%s\n' 'XPS 13 9350' >"${test_root}/dmi/product_name"
printf '%s\n' connected >"${test_root}/drm/card0-eDP-1/status"
printf '%s\n' Mains >"${test_root}/power/AC/type"
printf '%s\n' 1 >"${test_root}/power/AC/online"
: >"${test_root}/gdctl.log"
: >"${test_root}/gsettings.log"

panel_env=(
	"HOME=${test_root}/home"
	"XDG_CONFIG_HOME=${test_root}/config"
	"XDG_STATE_HOME=${test_root}/state"
	"FINITE_PANEL_DEFAULT_CONFIG=${panel_config}"
	"FINITE_PANEL_DMI_ROOT=${test_root}/dmi"
	"FINITE_PANEL_DRM_ROOT=${test_root}/drm"
	"FINITE_PANEL_POWER_SUPPLY_ROOT=${test_root}/power"
	"FINITE_PANEL_GDCTL=${test_root}/bin/gdctl"
	"FINITE_PANEL_GDBUS=${test_root}/bin/gdbus"
	"FINITE_PANEL_GSETTINGS=${test_root}/bin/gsettings"
	"MOCK_GDCTL_STATE=${test_root}/gdctl-state"
	"MOCK_GDCTL_LOG=${test_root}/gdctl.log"
	"MOCK_GSETTINGS_LOG=${test_root}/gsettings.log"
)

write_panel_state 1920x1200@60.000 1920x1200@120.000+vrr
env "${panel_env[@]}" FINITE_PANEL_AMBIENT_BRIGHTNESS_MIGRATION_ENABLED=false \
	MOCK_ON_BATTERY=false bash "${panel_helper}" --apply >/dev/null
grep -qF -- '--scale 1.25 --transform normal --x 0 --y 0 --monitor eDP-1 --mode 1920x1200@120.000+vrr' \
	"${test_root}/gdctl.log" || fail 'AC policy did not select the 120 Hz VRR mode'

: >"${test_root}/gdctl.log"
write_panel_state 1920x1200@120.000+vrr 1920x1200@60.000
env "${panel_env[@]}" FINITE_PANEL_AMBIENT_BRIGHTNESS_MIGRATION_ENABLED=false \
	MOCK_ON_BATTERY=true bash "${panel_helper}" --apply >/dev/null
grep -qF -- '--mode 1920x1200@60.000' "${test_root}/gdctl.log" ||
	fail 'battery policy did not select the 60 Hz mode'

install -d "${test_root}/drm/card0-DP-1"
printf '%s\n' connected >"${test_root}/drm/card0-DP-1/status"
: >"${test_root}/gdctl.log"
env "${panel_env[@]}" FINITE_PANEL_AMBIENT_BRIGHTNESS_MIGRATION_ENABLED=false \
	MOCK_ON_BATTERY=false bash "${panel_helper}" --apply >/dev/null 2>&1 || true
test ! -s "${test_root}/gdctl.log" || fail 'policy changed a multi-monitor layout'
rm -rf -- "${test_root}/drm/card0-DP-1"

write_panel_state 1920x1200@120.000+vrr 1920x1200@60.000
for _ in 1 2; do
	env "${panel_env[@]}" MOCK_ON_BATTERY=false bash "${panel_helper}" --apply >/dev/null
done
test "$(grep -cF 'set org.gnome.settings-daemon.plugins.power ambient-enabled true' "${test_root}/gsettings.log")" -eq 1
test -f "${test_root}/state/finite/dell-xps-9350-ambient-brightness-v1"
