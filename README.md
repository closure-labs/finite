# Purplefin

Purplefin is a custom Universal Blue image based on Bluefin:

```text
ghcr.io/projectbluefin/bluefin:stable
```

The image is built from this repository and published to:

```text
ghcr.io/declarative-dale/purplefin
```

## Versions, builds, and releases

`VERSION` is Purplefin's source version and is embedded in every image as the
`org.opencontainers.image.version` label and `/usr/share/purplefin/version`.
Normal builds resolve and verify Bluefin first, build from its immutable digest,
rechunk the result, push it once, and sign and attest the resulting Purplefin
digest. Profile inputs are hashed independently and the dynamic matrix includes
only images whose source, base, or managed RPM state changed.

The release workflow accepts a release version already present in `VERSION` and
the next development version. It first dispatches and waits for a forced,
all-profile release-candidate build. After release-environment approval it
verifies those published profiles and promotes their existing digests to immutable
`PROFILE-vVERSION` tags, creates the GitHub release and manifest, then commits
the requested `-dev.N` version to `main` and dispatches its build. Release
promotion never rebuilds an image.

## Declarative profile composition

Purplefin uses a Nix flake and Den aspects as the source of truth. The `base`,
hardware, and role aspects each define their bootc changes and optional Home
Manager changes once. Named profiles select those aspects; Nix validates the
inheritance graph and generates the build matrix, exact derived-module deltas,
profile catalog, Home Manager activation packages, and OSBuild Blueprints.

Bluefin Stable remains the complete upstream filesystem. Purplefin does not
reconstruct or selectively copy it: the common `base` image starts from the
verified upstream digest and adds all shared Purplefin changes. Hardware images
derive from that common base, and every role or role combination derives from
one hardware image.

Reusable workload modules include `developer` (DevOps tooling plus Rust),
`sales` (Thunderbird), `support` (Espanso and RustConn), `trainer` (Grist
Firefox launcher), `executive` (Vates Notes Firefox launcher), and `it`
(RustDesk). The Framework hardware module is intentionally a no-tuning
scaffold until model-specific settings are validated.

Purplefin composes one department with one hardware profile and emits one final
bootc image. The named `BUILD_PROFILE` selects an ordered module composition;
the common foundation is applied first, followed by workload and hardware
modules.

## Graphical installer

The installer workflow takes a published profile, verifies its GitHub Actions
Cosign signature, resolves it to an immutable digest, and embeds that exact
payload in an Anaconda ISO. It uses OSBuild's current `image-builder` CLI and
the supported `bootc-generic-iso` image type. A weekly trusted run builds the
generic installer and smoke-boots it with QEMU; maintainers can dispatch the
workflow for any published profile. See [installer/README.md](installer/README.md).

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
| `dell-xps-9350-intel` | Dell XPS 13 9350 policies, lid-aware privilege authentication, rEFInd, and the IPU7 camera stack. |

Every hardware profile also applies the shared hardware-security baseline:
fingerprint authentication, PAM U2F/FIDO2 support, YubiKey management, and
smart-card services. User-specific fingerprint enrollments and security-key
mappings remain local to each machine and are never built into an image.
The Dell profile makes `sudo` and polkit authentication lid-aware: an open lid
uses the normal fingerprint-first stack, while a closed or indeterminate lid
uses the local account password without attempting fingerprint authentication.

The default pair is the `base` department with `generic-x86_64` hardware. The
`generic-x86_64` and `latest` compatibility tags point to that same build. The
`dell-xps-9350-intel` compatibility tag points to the `support` department with
the Dell hardware profile. Departments and hardware profiles are independent
build inputs, but every published image contains exactly one of each; they are
not packages or layers selected by the installer. `bootc install`, `bootc
switch`, and subsequent upgrades track that single precomposed image tag.

The build workflow publishes every declared profile:

| Department | Hardware | Image tags |
| --- | --- | --- |
| `base` | `generic-x86_64` | `generic-x86_64`, `latest`, and `base-generic-x86_64` |
| `base` | `dell-xps-9350-intel` | `base-dell-xps-9350-intel` |
| `sales` | `generic-x86_64` | `sales-generic` |
| `sales` | `dell-xps-9350-intel` | `sales-dell-xps-9350-intel` |
| `support` | `generic-x86_64` | `support-generic` |
| `support` | `dell-xps-9350-intel` | `support-dell-xps-9350-intel` |
| combined Dale profile | `dell-xps-9350-intel` | `dale` and `dell-xps-9350-intel` |
| `developer` | `generic-x86_64` | `developer-generic` |
| `trainer` | `generic-x86_64` | `trainer-generic` |
| `executive` | `generic-x86_64` | `executive-generic` |
| `it` | `generic-x86_64` | `it-generic` |

On `main`, CI builds the generated matrix as a three-stage graph:

```text
verified ghcr.io/projectbluefin/bluefin:stable digest
└── base                         (all shared Purplefin changes)
    ├── base-generic             (generic hardware delta)
    │   ├── sales-generic
    │   ├── support-generic
    │   ├── developer-generic
    │   ├── trainer-generic
    │   ├── executive-generic
    │   └── it-generic
    └── base-dell-xps-9350-intel (Dell/IPU7 hardware delta)
        ├── sales-dell-xps-9350-intel
        ├── support-dell-xps-9350-intel
        └── dale
```

Nix computes a selective source fingerprint and exact module delta for every
profile. A shared-base change rebuilds the entire descendant closure; a
hardware change rebuilds only that hardware branch; and a role-only change
reuses the current immutable hardware parent. Buildah also publishes reusable
intermediate layers to the repository's `purplefin-build-cache` GHCR package.
The planner detects and repairs children left on an older parent after a partial
publish. Pull requests build complete images without package-write permission.

To change the graph, edit `nix/flake-modules/profiles.nix`; to change a reusable
feature, edit its `nix/aspects/<aspect>/` directory or the matching `bootc/`
module and overlay. Then run:

```bash
nix run .#generate
nix develop --command just format
nix flake check
nix develop --command tests/ci.sh
```

Generated `bootc/generated/image-matrix.json`, `bootc/generated/profile-catalog.json`,
and files under `installer/config/profiles` must not be edited by hand. OSBuild Blueprints can
describe supported bootc users and `/` or `/boot` filesystem customizations;
RPM composition remains in the bootc Containerfile/modules because bootc
Blueprints do not support package composition.

The source tree is intentionally split into only a few ownership boundaries:

```text
nix/aspects/<aspect>/   Den aspect and optional Home Manager customization
nix/flake-modules/     profile composition and exported flake outputs
bootc/modules/         build-time implementation for each aspect
bootc/overlays/        base, role, and hardware filesystem payloads
bootc/components/      reusable multi-role components such as devops
bootc/build/           full, derived, and planning entrypoints
bootc/generated/       Nix-generated catalogs consumed by CI and bootc builds
installer/             image-builder Containerfile, overlay, and Blueprints
tests/                 local and CI validation entrypoints
```

## Build Locally

```bash
just build-generic
just build-dell
just build-base-generic
just build-support-dell
```

The generic and Dell recipes build the two primary profiles. The remaining
recipes name their profile explicitly.

For an equivalent direct build:

```bash
base_digest="$(skopeo inspect --format '{{.Digest}}' docker://ghcr.io/projectbluefin/bluefin:stable)"
podman build \
  --build-arg BASE_REF="ghcr.io/projectbluefin/bluefin@${base_digest}" \
  --build-arg BUILD_PROFILE=dale \
  --build-arg PURPLEFIN_VERSION="$(<VERSION)" \
  --tag ghcr.io/declarative-dale/purplefin:dell-xps-9350-intel \
  .
```

## Switch To An Image

Select the complete department and hardware build you want. For example:

```bash
run0 bootc switch ghcr.io/declarative-dale/purplefin:generic-x86_64
run0 bootc switch ghcr.io/declarative-dale/purplefin:support-dell-xps-9350-intel
run0 bootc switch ghcr.io/declarative-dale/purplefin:dale
```

Reboot after switching. Switching changes the complete tracked image; bootc
does not combine a department tag with a separate hardware tag at installation
time.

The `latest` tag tracks the `base` + `generic-x86_64` image. The
`dell-xps-9350-intel` tag tracks the combined Dale profile.
The reusable `devops` component provides
Ghostty, VSCodium,
`packer`, `ansible`, `tofu`, and `bao`; both the support and development
departments reference it. The base department provides Git, Micro, `qemu-img`,
`qemu-tools`, common QEMU image block backends, and Fedora's complete
`podman-machine` runtime with the headless QEMU, `gvproxy`, and `virtiofsd`
helpers. Podman Machine is therefore available in every Purplefin profile
without host package layering or user-local helper binaries.
Terra's Bitwarden packages are excluded so future DNF operations cannot
reintroduce the desktop RPM after migration to Flatpak.

### Keep the laptop awake with the lid closed

Purplefin includes a reversible native systemd inhibitor. While connected to
AC power, start it before closing the lid:

```bash
purplefin-caffeinate on
purplefin-caffeinate status
```

Restore normal lid/suspend behavior with `purplefin-caffeinate off`. The unit
uses `systemd-inhibit` for both sleep and low-level lid handling and has
`ConditionACPower=true`, so it refuses to start on battery. It is not enabled at
boot and stops automatically when the user manager/session ends.

Before switching to an image containing the utility, start the same temporary
native inhibitor on Bluefin with:

```bash
systemd-run --user --unit=purplefin-caffeinate --collect \
  /usr/bin/systemd-inhibit --what=sleep:handle-lid-switch \
    --who=Purplefin --why='Lid-closed work session' --mode=block \
    /usr/bin/sleep infinity
```

Revoke it with `systemctl --user stop purplefin-caffeinate.service`; a reboot
also removes the transient unit.

Bitwarden desktop is installed system-wide from Bitwarden's verified Flathub
package, and the image includes Bitwarden's polkit policy for Linux
system-authentication unlock. The native `/usr/bin/bw` CLI remains a
Purplefin-built RPM in the bootc image: its official versioned archive and
GitHub-published SHA-256 digest are pinned in `bootc/packages/bitwarden-cli/package.env`.

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
this laptop. Generic profiles do not install its replacement modules, udev
rules, or camera-specific userspace configuration.

The implementation follows `svp7500-camera-fix-pack` v1.0.2 at commit
`e4c95452339b2d9803974a899c4f2da6e143891d`. The build verifies the IPU bridge,
IPU7, OV02C10, USBIO, and firmware capabilities required by the modular fixes.

The flow is:

1. The profile validates IPU7, OV02C10, IPU bridge, USBIO, and firmware support.
2. The image build compiles the fix-pack's patched
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
Firefox. Purplefin watches `profiles.ini` and configures profiles created after
login; restart a newly created profile once so Firefox reads its generated
`user.js`. Firefox should then show one internal camera instead of dozens of
non-working IPU7 inputs.

## What Is Tracked

- Common foundation → department → hardware composition with the selected
  department and hardware written into image metadata.
- A shared base containing Git, Micro, Fedora's FUSE 2 runtime,
  `wireguard-tools`, the NetworkManager connection editor, `qemu-img`,
  `qemu-tools`, common QEMU image block backends, `podman-machine`, its
  headless QEMU provider, and the Fedora-packaged `gvproxy` and `virtiofsd`
  helpers. The base also includes the complete Homebrew `Brewfile`, branding,
  and common Flatpak preinstalls such as Bitwarden, Nextcloud Desktop Client,
  Cameractrls, and Gear Lever. Fedora's `qemu-img` package supplies the core
  image tools; Fedora has no separate `qemu-img-core` subpackage.
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
- Bluefin's inherited Tailscale service, RPM repository configuration, setup
  hook, shell completion, and user-facing tips are preserved. Purplefin lists
  the Tailscale and Espanso RPMs in
  `bootc/config/independently-managed-rpms.list`, upgrades the installed subset
  from their repositories during image builds, and includes them in daily RPM
  probes for profiles where they are installed.
- Dell XPS 9350 Intel pinned SVP7500 fix-pack CVS/IPU bridge/HM1092 fixes,
  conditional INT3472 replacement, bridge
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
