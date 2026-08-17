# Dell XPS 13 9350

The `hardware-dell-xps-9350-intel` aspect configures the Dell XPS 13 9350 with
lid-aware authentication, battery charge thresholds, laptop-oriented TuneD
settings, automatic internal-panel refresh rates, rEFInd theming, and the IPU7
camera stack. Each hardware helper checks the system's Dell/XPS DMI identity.

## Lid-aware privilege authentication

At the start of each `sudo` or polkit authentication, the policy reads
systemd-logind's `LidClosed` property and the Dell ACPI lid state. An open lid
uses fingerprint-first authentication. A closed or indeterminate lid uses the
local account password.

Inspect the state and start a fresh authentication:

```bash
busctl get-property \
  org.freedesktop.login1 \
  /org/freedesktop/login1 \
  org.freedesktop.login1.Manager \
  LidClosed
cat /proc/acpi/button/lid/*/state
grep -H 'purplefin-dell-lid-auth' /etc/pam.d/{sudo,polkit-1}
sudo -k
sudo -v
```

## Battery charging

`purplefin-dell-xps-9350-battery.service` enables UPower's charge-threshold
policy and selects Dell's `Custom` charging mode with a 75–80% window.

Override the policy in `/etc/purplefin/dell-xps-9350-battery.conf`:

```ini
ENABLED=true
START_THRESHOLD=75
END_THRESHOLD=80
```

Restart and inspect the applied policy:

```bash
run0 systemctl restart purplefin-dell-xps-9350-battery.service
upower -i /org/freedesktop/UPower/devices/battery_BAT0 | \
  rg 'charge-(start|end)-threshold|charge-threshold-enabled'
cat /sys/class/power_supply/BAT0/charge_control_{start,end}_threshold
```

## Power profiles

GNOME and `powerprofilesctl` use TuneD. Performance mode maps to
`purplefin-dell-xps-9350-performance`, a laptop profile that configures CPU
energy preference, boost, and Dell's firmware platform profile.

```bash
powerprofilesctl set performance
tuned-adm active
cat /sys/firmware/acpi/platform_profile
cat /sys/devices/system/cpu/cpufreq/policy0/energy_performance_preference
```

## Internal display

The graphical-session service selects `1920x1200@120.000+vrr` on AC power and
`1920x1200@60.000` on battery. It preserves the panel's scale, transform,
position, and primary state. A user configuration can override mode selectors,
polling, ambient brightness, and the enabled state:

```bash
mkdir -p ~/.config/purplefin
cp /usr/share/purplefin/dell-xps-9350-panel.conf \
  ~/.config/purplefin/dell-xps-9350-panel.conf
systemctl --user restart purplefin-dell-xps-9350-panel.service
gdctl show --modes --properties
```

## IPU7 camera

The camera stack targets Lunar Lake IPU7 (`8086:645d`), the Synaptics
SVP7500/Intel CVS bridge (`INTC10DE`), and OV02C10 (`OVTI02C1`). Purplefin
builds the pinned SVP7500 fix-pack's `intel_cvs`, `ipu_bridge`, and HM1092
modules for the image kernel. It selects the included INT3472 provider when it
preserves the IR flood LED interface.

Fedora's libcamera, IPA proxy, PipeWire plugin, and GPU SoftISP provide the
userspace pipeline. A checksum-pinned OV02C10 Simple IPA helper supplies sensor
gain conversion, a 10-bit black pedestal, and baseline color correction.
WirePlumber publishes the OV02C10 camera while filtering the raw IPU7 capture
endpoints and the monochrome HM1092 source. Firefox profiles use PipeWire for
camera discovery.

Inspect the running stack:

```bash
uname -r
cat /usr/share/purplefin/dell-ipu7/source-provenance
cat /usr/share/purplefin/dell-ipu7/libcamera-ipa-provenance
modinfo -n intel_cvs
modinfo -n ipu_bridge
modinfo -n hm1092
readlink -f /sys/bus/i2c/devices/i2c-INTC10DE:00/driver
readlink -f /sys/bus/i2c/devices/i2c-OVTI02C1:00/driver
journalctl -k -b | rg -i 'ipu7|intel.cvs|hm1092|ov02c10|firmware'
cam -l
```

The [Secure Boot guide](dell-xps-9350-secure-boot.md) documents module
provenance, provider selection, and signature policy.
