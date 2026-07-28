# Purplefin

Purplefin is a custom Universal Blue image based on Bluefin:

```text
ghcr.io/projectbluefin/bluefin:stable
```

The image is built from this repository and published to:

```text
ghcr.io/declarative-dale/purplefin
```

## Build-Time Composition

Purplefin's public build input is a named `BUILD_PROFILE`. Each profile is an
ordered list of reusable modules and exactly one hardware module. The primary
profiles are `base-generic` and `dale`; Dale combines base, sales, trainer,
support, and Dell XPS 13 9350 Intel/IPU7 hardware while retaining Bluefin's
GNOME desktop.
Legacy `BUILD_ROLE` plus
hardware-valued `BUILD_PROFILE` inputs remain available for migration.

Reusable workload modules include `developer` (DevOps tooling plus Rust),
`sales` (Thunderbird), `support` (Espanso and RustConn), `trainer` (Grist
Firefox launcher), `executive` (Vates Notes Firefox launcher), and `it`
(RustDesk). The Framework hardware module is intentionally a no-tuning
scaffold until model-specific settings are validated.

Purplefin composes one department with one hardware profile and emits one final
bootc image. The common foundation is applied first, followed by the selected
department and hardware profile:

- `BUILD_ROLE` selects the department workload. Its historical name is retained
  for build compatibility.
- `BUILD_PROFILE` selects the hardware overlay. The historical variable name is
  retained for compatibility, but it now means hardware rather than the whole
  image personality.

## Graphical installer pilot

The optional Purplefin installer ISO uses Anaconda for storage, accounts, and
networking, then installs one verified, prebuilt bootc image. It does not layer
packages locally. After networking is configured, the Purplefin screen offers
the Base, Sales, and Support presets; on a detected Dell XPS 13 9350 it also
offers Dale. The selected GHCR tag is verified with the repository's GitHub
Actions cosign identity and resolved to an immutable digest before installation.
Unknown hardware safely receives a generic image.

The ISO is intentionally built on demand from the **Build Purplefin installer
ISO** workflow. See [installer/README.md](installer/README.md) for the source
selection interface and image-builder requirements.

| Department | Workload |
| --- | --- |
| `base` | Shared image foundation, including Git, Micro, and QEMU disk-image tooling. |
| `support` | Base plus the shared `devops` component, Espanso, and RustConn. |
| `development` | Base plus the shared `devops` component. |

| Reusable component | Workload | Referenced by |
| --- | --- | --- |
| `devops` | Ghostty and its defaults, VSCodium, Ansible, Packer, OpenTofu, OpenBao, and their supporting configuration. | `support`, `development` |

| Hardware profile | Overlay |
| --- | --- |
| `generic-x86_64` | Generic x86-64 hardware with no vendor-specific overlay. |
| `desktop-x86_64` | Neutral generic x86-64 desktop scaffold for future hardware policy. |
| `lenovo-generic` | Neutral Lenovo scaffold for future hardware policy. |
| `dell-xps-9350-intel` | Dell XPS 13 9350 policies, lid-aware privilege authentication, rEFInd, and the IPU7 camera stack. |
| `dell-xps-9350-intel-no-ipu7` | Dell XPS 13 9350 test overlay with its non-camera and lid-aware authentication policies and Bluefin's included kernel, but no IPU7 camera integration. |

Every hardware profile also applies the shared hardware-security baseline:
fingerprint authentication, PAM U2F/FIDO2 support, YubiKey management, and
smart-card services. User-specific fingerprint enrollments and security-key
mappings remain local to each machine and are never built into an image.
Both Dell profiles make `sudo` and polkit authentication lid-aware: an open lid
uses the normal fingerprint-first stack, while a closed or indeterminate lid
uses the local account password without attempting fingerprint authentication.

The default pair is the `base` department with `generic-x86_64` hardware. The
`generic-x86_64` and `latest` compatibility tags point to that same build. The
`dell-xps-9350-intel` compatibility tag points to the `support` department with
the Dell hardware profile. Departments and hardware profiles are independent
build inputs, but every published image contains exactly one of each; they are
not packages or layers selected by the installer. `bootc install`, `bootc
switch`, and subsequent upgrades track that single precomposed image tag.

The build workflow publishes these representative combinations:

| Department | Hardware | Image tags |
| --- | --- | --- |
| `base` | `generic-x86_64` | `generic-x86_64`, `latest`, and `base-generic-x86_64` |
| `support` | `dell-xps-9350-intel` | `dell-xps-9350-intel` and `support-dell-xps-9350-intel` |
| `support` | `lenovo-generic` | `support-lenovo-generic` |
| `development` | `desktop-x86_64` | `development-desktop-x86_64` |

## Build Locally

```bash
just build-generic
just build-dell
just build-dell-no-ipu7
just build-base-generic
just build-support-dell
just build-support-lenovo
just build-development-desktop
```

The first three recipes are compatibility entry points: generic builds
`base` + `generic-x86_64`, while both Dell recipes build `support` with the
corresponding Dell hardware profile. The remaining recipes name their
department and hardware combinations explicitly.

The `just` targets inspect Bluefin's `ostree.linux` label and write the matching
kernel label into the derived image. For an equivalent direct build, resolve
that value first:

```bash
base_kernel="$(skopeo inspect docker://ghcr.io/projectbluefin/bluefin:stable | jq -er '.Labels["ostree.linux"]')"
target_kernel="$(build_files/select-ostree-linux.sh dell-xps-9350-intel "${base_kernel}")"
podman build \
  --build-arg BUILD_ROLE=support \
  --build-arg BUILD_PROFILE=dell-xps-9350-intel \
  --build-arg PURPLEFIN_OSTREE_LINUX="${target_kernel}" \
  --label "ostree.linux=${target_kernel}" \
  --tag ghcr.io/declarative-dale/purplefin:dell-xps-9350-intel \
  .
```

Both Dell profiles keep Bluefin's included kernel unchanged. The full camera
profile builds its small set of SVP7500 replacement modules against that exact
kernel; the no-IPU7 test profile adds no camera kernel modules at all.

## Switch To An Image

Select the complete department and hardware build you want. For example:

```bash
run0 bootc switch ghcr.io/declarative-dale/purplefin:generic-x86_64
run0 bootc switch ghcr.io/declarative-dale/purplefin:support-dell-xps-9350-intel
run0 bootc switch ghcr.io/declarative-dale/purplefin:development-desktop-x86_64
```

Reboot after switching. Switching changes the complete tracked image; bootc
does not combine a department tag with a separate hardware tag at installation
time.

The `latest` tag tracks the `base` + `generic-x86_64` image. The
`dell-xps-9350-intel` tag tracks `support` + Dell IPU7. The local
`build-dell-no-ipu7` compatibility recipe produces the `support` + Dell
no-camera test image. Both follow Bluefin's kernel without a Dell-specific
kernel repository or version override. The reusable `devops` component provides
Ghostty, VSCodium,
`packer`, `ansible`, `tofu`, and `bao`; both the support and development
departments reference it. The base department provides Git, Micro, `qemu-img`,
`qemu-tools`, and common QEMU image block backends.
Inherited Tailscale packages, services, repositories, setup hooks, and
user-facing tips are removed from every composition.
Terra's Bitwarden packages are excluded so future DNF operations cannot
reintroduce the desktop RPM after migration to Flatpak.

Bitwarden desktop is installed system-wide from Bitwarden's verified Flathub
package, and the image includes Bitwarden's polkit policy for Linux
system-authentication unlock. The native `/usr/bin/bw` CLI remains a
Purplefin-built RPM in the bootc image: its official versioned archive and
GitHub-published SHA-256 digest are pinned in `build_files/bitwarden-cli.env`.

### Migrating Bitwarden from the layered RPM

Purplefin images built before this change layer Bitwarden's desktop RPM on the
host during first boot. The replacement image preinstalls the verified Flatpak
and carries a one-time migration task that removes the old RPM layer without
deleting its per-user data.

Before upgrading, make sure the vault has completed a sync. Then deploy and
boot the updated image:

```bash
run0 bootc upgrade
run0 systemctl reboot
```

On the first boot into the updated image,
`purplefin-firstboot-rpm-ostree.service` detects the legacy `bitwarden` layer
and stages its removal. If a removal was staged, reboot once more:

```bash
systemctl status purplefin-firstboot-rpm-ostree.service
run0 systemctl reboot
```

The Flatpak uses `~/.var/app/com.bitwarden.desktop/` rather than the native
client's `~/.config/Bitwarden/` state. Launch the Flatpak and sign in again;
keep the old directory until the new client has synced and all expected vault
items are present. The native CLI keeps its existing configuration and remains
available as `/usr/bin/bw`.

Verify the completed migration with:

```bash
! rpm -q bitwarden
flatpak info --system com.bitwarden.desktop
rpm -q purplefin-bitwarden-cli
bw --version
test -f /usr/share/polkit-1/actions/com.bitwarden.Bitwarden.policy
```

If the one-time task did not remove the old layer, remove it explicitly and
reboot before launching the Flatpak:

```bash
run0 rpm-ostree uninstall bitwarden
run0 systemctl reboot
flatpak install --system flathub com.bitwarden.desktop
```

After migration, enable **Unlock with system authentication** in Bitwarden if
desired. A rollback to a pre-migration bootc deployment may temporarily expose
both desktop packages because Flatpak state persists outside the bootc image;
use the Flatpak, then upgrade forward again.

### Migrating from the Nextcloud AppImage

Purplefin images built before this change contain a Nextcloud AppImage in the
immutable `/usr` deployment. Deploy the updated image and reboot to remove the
AppImage, its `/usr/bin/nextcloud` link, desktop file, icon, and provenance file.
The shared Flatpak preinstall service installs the replacement automatically.
If it has not run yet, install the replacement explicitly:

```bash
flatpak install --system flathub com.nextcloud.desktopclient.nextcloud
```

Before rebooting, quit the old client with `pkill -x nextcloud` if it is still
running. After rebooting, verify the migration with:

```bash
test ! -e /usr/libexec/purplefin/appimages/Nextcloud.AppImage
test ! -e /usr/share/purplefin/nextcloud-appimage.provenance
flatpak info com.nextcloud.desktopclient.nextcloud
```

Nextcloud's Flatpak keeps application state in its sandbox, so launch it and
configure the account again if the existing AppImage settings are not imported.

## Dell XPS 13 9350 Hardware Policies

Both Dell profiles carry the non-camera policies below. Every hardware helper
checks for `Dell Inc.` / `XPS 13 9350` DMI data before changing anything.

### Lid-aware privilege authentication

At the start of each new `sudo` or polkit authentication, the Dell policy reads
systemd-logind's `LidClosed` property and cross-checks
`/proc/acpi/button/lid/*/state` when the Dell ACPI state is available. A
known-open lid uses the normal authselect-managed stack, including
fingerprint-first authentication. Any reported closed or conflicting state—or
the absence of an unambiguous open state—uses only the local Unix password.

Because `run0` and `pkexec` authenticate through polkit, the same behavior
applies to them and to graphical polkit prompts. Login and screen-unlock PAM
services are unchanged. The lid is sampled when a new prompt begins; closing
the lid does not replace an authentication method in a prompt that is already
open, and cached sudo or polkit authorization may avoid a new prompt entirely.

Inspect the state and force a fresh sudo prompt with:

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

### Battery charging

`purplefin-dell-xps-9350-battery.service` enables UPower's charge-threshold
policy, selects Dell's `Custom` charging mode, and verifies a 75-80% charging
window. This favors battery longevity over maximum unplugged runtime. The
DMI-specific hardware database entry also makes the same limits explicit to
UPower.

Override the policy in `/etc/purplefin/dell-xps-9350-battery.conf`:

```ini
ENABLED=true
START_THRESHOLD=75
END_THRESHOLD=80
```

`ENABLED=false` prevents the service from applying the policy; it does not
undo thresholds already stored by the firmware. Use Dell firmware settings or
UPower to select a different charging policy when opting out. Verify an applied
policy with:

```bash
run0 systemctl restart purplefin-dell-xps-9350-battery.service
upower -i /org/freedesktop/UPower/devices/battery_BAT0 | \
  rg 'charge-(start|end)-threshold|charge-threshold-enabled'
cat /sys/class/power_supply/BAT0/{charge_types,charge_control_start_threshold,charge_control_end_threshold}
```

### Power profiles

GNOME and `powerprofilesctl` continue to use TuneD. Balanced mode retains
Bluefin's normal AC/battery behavior. Performance mode now maps to
`purplefin-dell-xps-9350-performance`, which inherits TuneD's balanced laptop
profile and changes only CPU energy preference, boost, and Dell's firmware
platform profile. It deliberately omits the server-oriented disk, VM, sysctl,
and `min_perf_pct=100` settings from `throughput-performance`.

```bash
powerprofilesctl set performance
tuned-adm active
cat /sys/firmware/acpi/platform_profile
cat /sys/devices/system/cpu/cpufreq/policy0/energy_performance_preference
```

### Internal display and ambient brightness

The graphical-session user service selects the built-in FHD+ panel's
`1920x1200@120.000+vrr` mode on AC and fixed `1920x1200@60.000` mode on battery. It
discovers the exact advertised mode, preserves scale, transform, position, and
primary state, and refuses to act whenever an external connector or a complex
layout is present. A one-time migration enables GNOME ambient brightness; any
later choice made in GNOME Settings remains authoritative.

Copy `/usr/share/purplefin/dell-xps-9350-panel.conf` to
`~/.config/purplefin/dell-xps-9350-panel.conf` to change the mode selectors,
poll interval, ambient-brightness migration, or `PANEL_POLICY_ENABLED`. Apply a
change with:

```bash
systemctl --user restart purplefin-dell-xps-9350-panel.service
gdctl show --modes --properties
```

The fix-pack modules are currently unsigned. Read the
[Dell XPS 13 9350 Secure Boot note](docs/dell-xps-9350-secure-boot.md) before
enabling enforcement; there is no automatic handoff to mainline `cvs`.

## Dell IPU7 Camera Flow

The Dell XPS 9350 Intel profile targets the Lunar Lake IPU7 (`8086:645d`),
Synaptics SVP7500/Intel CVS (`INTC10DE`), and OV02C10 (`OVTI02C1`) camera in
this laptop. The generic and `dell-xps-9350-intel-no-ipu7` profiles do not
install its replacement modules, udev rules, or camera-specific userspace
configuration.

The implementation follows `svp7500-camera-fix-pack` v1.0.2 at commit
`e4c95452339b2d9803974a899c4f2da6e143891d`. Purplefin keeps Bluefin's exact
included kernel and verifies that its IPU bridge, IPU7, OV02C10, and USBIO
features are enabled. It does not enable a COPR or install a replacement
kernel. The build stops if the included kernel cannot accept the modular
fixes.

The flow is:

1. The profile retains the inherited Bluefin kernel and validates its IPU7,
   OV02C10, IPU bridge, USBIO, and firmware support.
2. Against that exact kernel, the image build compiles the fix-pack's patched
   `intel_cvs`, `ipu_bridge`, and `hm1092` modules. It installs the patched
   INT3472 module only when the in-tree driver does not already publish the IR
   flood LED; replacing a newer in-tree INT3472 would break the illuminator.
   Kbuild uses the same GCC or Clang family recorded by the inherited kernel,
   avoiding a compiler mismatch without modifying the fix-pack sources.
   The exact source commit and provider choice are recorded in
   `/usr/share/purplefin/dell-ipu7/source-provenance`.
   The rebuilt initramfs explicitly installs the detected `ipu7_fw.bin`
   variant and verifies its presence, since the in-tree IPU7 module does not
   advertise that firmware to Dracut.
3. Fedora's `libcamera`, `libcamera-ipa`, `libcamera-tools`, and
   `pipewire-plugin-libcamera` provide the Simple pipeline, isolated IPA proxy,
   and GPU SoftISP. The Dell profile builds only a patched Simple IPA module
   from the matching, checksum-pinned libcamera source. Its OV02C10 helper
   converts the sensor's 1/16-step gain codes into physical gain and supplies
   the 10-bit `0x40` black pedestal. The module lives in a separate Purplefin
   search path and runs through Fedora's stock isolated proxy; Fedora's
   libraries and other IPA modules remain untouched. Purplefin also supplies
   an OV02C10 tuning profile with a baseline color-correction matrix, avoiding
   libcamera's uncalibrated identity-matrix fallback. Purplefin does not add a
   PSYS DKMS tree, full replacement libcamera stack, v4l2loopback device, or
   proprietary camera HAL.
4. The fix-pack's udev policy disables autosuspend for the `06cb:0701`
   SVP7500 bridge and grants the `video` group access to an INT3472 IR flood
   LED when the laptop exposes one. Module loading and sensor binding otherwise
   use the kernel's normal device discovery; there is no Purplefin rebind
   service or forced module-load list.
5. WirePlumber suppresses raw V4L2 devices whose description is `ipu7`.
   Those are ISYS capture endpoints, not webcams. It also suppresses the
   libcamera HM1092 source, whose monochrome IR data is not usable through the
   Bayer-oriented Simple pipeline. The OV02C10 remains the single camera
   published to desktop applications. A user service configures each Flathub
   Firefox profile to use its PipeWire camera backend, preventing Firefox from
   bypassing WirePlumber and enumerating the raw V4L2 nodes.

The fix-pack's mainline CVS evaluation is important: Linux 7.2's `cvs` driver
expects to sit inside a firmware-described media graph, while this SVP7500
platform uses CVS as a control-plane-only ownership and MIPI configuration
bridge. Purplefin therefore continues to install the pinned external
`intel_cvs` on newer kernels instead of switching providers based on a version
number.

Runtime verification on the Dell laptop:

```bash
uname -r
cat /usr/share/purplefin/dell-ipu7/source-provenance
cat /usr/share/purplefin/dell-ipu7/libcamera-ipa-provenance
modinfo -n intel_cvs
modinfo -n ipu_bridge
modinfo -n hm1092
readlink -f /sys/bus/i2c/devices/i2c-INTC10DE:00/driver
readlink -f /sys/bus/i2c/devices/i2c-OVTI02C1:00/driver
journalctl -k -b | grep -Ei 'ipu7|intel.cvs|hm1092|ov02c10|firmware'
cam -l
rg 'media.webrtc.camera.allow-pipewire' \
  ~/.var/app/org.mozilla.firefox/config/mozilla/firefox/*/user.js
```

`cam -l` should report the OV02C10 RGB sensor and the HM1092 IR sensor. After
restarting WirePlumber, its graph should contain no raw V4L2 devices described
as `ipu7`, no HM1092 libcamera source, and one OV02C10 camera source. After
Firefox has created a profile, log out and back in (or run
`systemctl --user start purplefin-firefox-pipewire-camera.service`) and restart
Firefox. Firefox should then show one internal camera instead of dozens of
non-working IPU7 inputs.

## What Is Tracked

- Common foundation → department → hardware composition with the selected
  department and hardware written into image metadata.
- A shared base containing Git, Micro, Fedora's FUSE 2 runtime,
  `wireguard-tools`, the NetworkManager connection editor, `qemu-img`,
  `qemu-tools`, common QEMU image block backends, the complete Homebrew
  `Brewfile`, branding, and common Flatpak preinstalls such as Bitwarden,
  Nextcloud Desktop Client, Cameractrls, and Gear Lever. Fedora's `qemu-img`
  package supplies the core image tools; Fedora has no separate
  `qemu-img-core` subpackage.
- Bitwarden's verified desktop Flatpak, polkit policy, legacy RPM
  migration, and official native CLI wrapped in a Purplefin-built RPM from a
  pinned archive and SHA-256 digest.
- A centralized first-boot rpm-ostree runner with ordered tasks and
  `/var/lib/purplefin/firstboot/*.done` markers. It stops when a task stages a
  deployment so later tasks run after the required reboot.
- The reusable `devops` component's Ghostty defaults, VSCodium Flatpak,
  Ansible, Packer, OpenTofu, OpenBao, HashiCorp repository, and OpenBao
  state-directory policy; both support and development reference it.
- The support department's graphical-session-bound Espanso service and
  capability and RustConn Flatpak, in addition to the shared `devops`
  component.
- Removal of inherited Tailscale packages, enabled services, RPM repository
  configuration, setup hooks, and user-facing tips from every composition.
- Dell XPS 9350 Intel use of Bluefin's included kernel, pinned SVP7500 fix-pack
  CVS/IPU bridge/HM1092 fixes, conditional INT3472 replacement, bridge
  autosuspend protection, an isolated OV02C10 helper layered over Fedora
  libcamera, and WirePlumber filtering for raw IPU7 endpoints.
- Dell XPS 9350 Intel lid-aware password/fingerprint routing for sudo and
  polkit, DMI-gated 75-80% UPower/Dell Custom charging, a laptop-safe TuneD
  Performance profile, AC/battery internal-panel refresh policy, and one-time
  user-overridable ambient-brightness enablement.
- A shared hardware-security baseline for every hardware profile, including
  fingerprint authentication, PAM U2F/FIDO2, YubiKey management, and smart-card
  services.
- Dell XPS 9350 Intel rEFInd Regular Dark theme staging plus an idempotent boot-time installer that enables it when `/boot/efi/EFI/refind/refind.conf` is present.
- User-specific PAM U2F key mappings are not included. After switching, create
  the configuration directory and register a key with
  `mkdir -p ~/.config/Yubico && pamu2fcfg > ~/.config/Yubico/u2f_keys`.

## What Is Not Tracked

This public repo intentionally excludes credentials, biometric enrollments,
SSH/GPG keys, machine identity, private dotfiles, and user-specific systemd
control files.

## Development Checks

```bash
just check
```
