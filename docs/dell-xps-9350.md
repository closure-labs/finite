# Dell XPS 13 9350

The `dell-xps-9350-intel` hardware aspect configures lid-aware authentication,
battery thresholds, TuneD power profiles, display refresh rates, and the IPU7
camera stack. Helpers verify the Dell/XPS DMI identity before applying changes.

## Boot branding

The Dell image installs Finite's dark rEFInd theme on the EFI system partition.
Finite entries use the canonical Finite mark instead of the former planet
artwork. After an entry is selected, Plymouth uses the same mark while the
system boots; GDM and shared image branding use matching derivatives.

The rEFInd installer runs through `finite-refind-theme.service`. Inspect it with:

```bash
systemctl status finite-refind-theme.service
journalctl -u finite-refind-theme.service -b
```

## Authentication

An open lid uses fingerprint-first authentication for `sudo` and polkit. A
closed or unknown lid uses the local account password.

```bash
busctl get-property \
  org.freedesktop.login1 \
  /org/freedesktop/login1 \
  org.freedesktop.login1.Manager \
  LidClosed
cat /proc/acpi/button/lid/*/state
grep -H finite-dell-lid-auth /etc/pam.d/{sudo,polkit-1}
sudo -k
sudo -v
```

## Battery thresholds

The default custom charging window is 75–80%. Override it in
`/etc/finite/dell-xps-9350-battery.conf`:

```ini
ENABLED=true
START_THRESHOLD=75
END_THRESHOLD=80
```

Apply and inspect it:

```bash
sudo systemctl restart finite-dell-xps-9350-battery.service
upower -i /org/freedesktop/UPower/devices/battery_BAT0 | \
  rg 'charge-(start|end)-threshold|charge-threshold-enabled'
cat /sys/class/power_supply/BAT0/charge_control_{start,end}_threshold
```

## Power profile

Performance mode uses `finite-dell-xps-9350-performance` through TuneD:

```bash
powerprofilesctl set performance
tuned-adm active
cat /sys/firmware/acpi/platform_profile
cat /sys/devices/system/cpu/cpufreq/policy0/energy_performance_preference
```

## Display

The internal panel uses `1920x1200@120.000+vrr` on AC and
`1920x1200@60.000` on battery. Copy the default configuration to override mode
selectors, polling, ambient brightness, or enablement:

```bash
mkdir -p ~/.config/finite
cp /usr/share/finite/dell-xps-9350-panel.conf \
  ~/.config/finite/dell-xps-9350-panel.conf
systemctl --user restart finite-dell-xps-9350-panel.service
gdctl show --modes --properties
```

## IPU7 camera

The image contains the selected `intel_cvs`, `ipu_bridge`, HM1092, INT3472,
libcamera, PipeWire, and OV02C10 IPA components. Inspect the active stack with:

```bash
uname -r
cat /usr/share/finite/dell-ipu7/source-provenance
cat /usr/share/finite/dell-ipu7/libcamera-ipa-provenance
modinfo -n intel_cvs ipu_bridge hm1092
readlink -f /sys/bus/i2c/devices/i2c-INTC10DE:00/driver
readlink -f /sys/bus/i2c/devices/i2c-OVTI02C1:00/driver
journalctl -k -b | rg -i 'ipu7|intel.cvs|hm1092|ov02c10|firmware'
cam -l
```

See [Secure Boot status](dell-xps-9350-secure-boot.md) for the camera module
signature policy.
