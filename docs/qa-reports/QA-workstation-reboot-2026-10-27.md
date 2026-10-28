# Workstation reboot review — 2026-10-27

Reviewed the boot beginning approximately 20:08 CDT on `vatesxps` after the
Foundation migration. This was a diagnostic review; no workstation configuration
was changed and no services were restarted.

## Current health

- Both `systemctl --failed` and `systemctl --user --failed` returned zero units.
- Foundation 0.5.1 remains locked to `2d3230b3bdfe73c739385398468bdb648d53a0f8`,
  with `main` as the declared input reference.
- Active Home Manager generation:
  `/nix/store/z1bdsp410s9b5rf5wk7588156aanybw1-home-manager-generation`.
- Espanso, the Dell panel policy, PipeWire, WirePlumber and Hermes are running.
  The Flatpak installation oneshot completed successfully.
- GNOME, GTK and main desktop portal services are running successfully. Their
  initial dependency failures at 20:08:57 recovered by 20:09:00.
- The login keyring is unlocked (`org.freedesktop.Secret.Collection.Locked` is
  false). GNOME Shell currently owns the SystemPrompter D-Bus name. Earlier
  prompter failures occurred before the graphical session was ready.
- Direct rendering is enabled using Intel Lunar Lake / Mesa 26.2.3, OpenGL 4.6.
- PipeWire exposes the OV02C10 as **Built-in Front Camera**. WirePlumber has
  `LIBCAMERA_IPA_MODULE_PATH=/usr/lib64/libcamera/ipa` loaded from the Foundation
  user drop-in. No camera frames were captured during this review.
- Approximately 27 GiB is available on the writable system volume. `/tmp` has
  approximately 7.6 GiB free. The composefs root reporting 100% is its immutable
  image, not exhaustion of the writable volume.
- No systemd-coredump entries were recorded for this boot.

## Confirmed failures and stale configuration

| Finding | Evidence and effect | Follow-up |
| --- | --- | --- |
| Old 1Password browser integration paths | Sixteen native-messaging manifests across Firefox and Chromium-family configuration directories still point to `/usr/lib/opt/1Password/1Password-BrowserSupport`, which does not exist. The Firefox example is `~/.mozilla/native-messaging-hosts/com.1password.1password.json`. The GUI launches, but these manifests cannot launch their browser integration helper. | Configure the native host for the installed Nix distribution and verify browser integration, rather than retaining the removed RPM path. |
| Gear Lever autostart still targets Flatpak | `~/.config/autostart/it.mijorus.gearlever.desktop` executes `flatpak run ... it.mijorus.gearlever --fetch-updates`. That Flatpak is absent; the journal records `app/it.mijorus.gearlever/x86_64/master not installed`. A native Gear Lever desktop entry is present in the Nix profile. | Replace or retire the obsolete Flatpak autostart entry while preserving the desired native startup behavior. |
| Claude deep-link handler points into a removed Nix package | `~/.local/share/applications/claude-code-url-handler.desktop` references the nonexistent `/nix/store/sfinjp9bq5c2w57zn2r6n8m3hay5hh0y-claude-code-2.1.273/bin/.claude-unwrapped`. `~/.config/mimeapps.list` still selects it for `claude-cli:` URLs. | Regenerate the handler for the intended installed Claude package, or remove the obsolete association if no longer needed. |
| Custom Command Menu extension is broken in the OS image | `gnome-extensions info custom-command-list@storageb.github.com` reports `State: ERROR`. Its schema XML exists under `/usr/share/gnome-shell/extensions/.../schemas`, but `gschemas.compiled` is absent. The journal contains the corresponding enable exception. | Compile the schema during image packaging; disabling the extension is an optional local workaround. |
| Foundation automatic update remains broken | `foundation home update --check` exits with `Main did not resolve to an immutable Foundation source`. The installed helper requires `narHash` in `nix flake metadata` output, while this installed Nix omits that field there. | Fix source resolution in Foundation. The main reference and immutable consumer lock themselves are intact. |
| Installed Finite update hook uses the removed command interface | `/usr/share/ublue-os/just/60-custom.just` still invokes `finite-home-update`, which Foundation 0.5.1 replaced with `foundation home update`. | Update the Finite image integration, together with the Foundation updater fix. The complete OS update command was not run during this review. |

## Leftovers that are currently contained

- `/etc/libcamera/configuration.yaml` still selects
  `/var/lib/finite/libcamera/ipa`, containing a September 21 IPA module. Foundation's
  diagnostic reproduces its ABI failure and verifies that the host IPA restores
  camera format enumeration. The active user WirePlumber override bypasses it.
  Keep that working override until the stale OS camera configuration is fixed.
  Direct clients that do not use this override remain exposed to the old path.
- Bitwarden launches successfully, but logs a permission error when it tries to
  rewrite its Home Manager owned autostart file. Home Manager already supplies
  that launcher. Native messaging falls back from hard links to successful
  copies across filesystems; those fallback messages do not mean installation
  failed.
- The existing friendly-audio-names WirePlumber configuration matches the
  currently exposed HDMI sinks. The raw IPU7-node and IR-camera filters match
  the intended camera composition. No evidence justifies removing these files.
- No broken symlinks were found in the checked autostart, systemd user,
  environment, WirePlumber, application-launcher or user D-Bus directories.
  A separate scan of 21 store references in active launchers/unit/environment
  files found the Claude handler issue above.
- `home-manager.previous.*` directories are recovery copies, not active imports.
  The empty first-login service drop-in directory has no effective override.
- Explicit capabilities now repeat several capabilities implied by the roles.
  They compose through Foundation's deduplicated union; they are not a startup
  failure, though explicitly selected capabilities will persist if roles change.

## Other boot diagnostics

Dash to Dock and Blur My Shell produced layout/theme warnings during startup.
There was no GNOME Shell crash recorded. AirPlay discovery timed out once for
the advertised MacBook audio device; PipeWire and the local speaker remain active.
The default microphone is muted and saved preferred audio endpoints refer to a
Bluetooth device that is not currently present; PipeWire selected local fallback
devices.

OS logs also contain missing optional udev groups (`plugdev`, `nintendo_switch`),
early-boot group-resolution messages, tmpfiles ordering/path warnings, Intel LPM
missing scheduler controls, and SELinux denials involving `lsblk` and `chcon`.
Core audio/video/input/render groups resolve after boot. These messages are OS
integration follow-ups; this review did not establish a current application
failure caused by them, and no security policy was changed.

## Source review correction — 2026-10-27

The earlier finding that the installed update hook invokes a removed command was
incomplete. `/usr/bin/finite-home-update` exists and executes the image-bundled
Foundation 0.3.3 source. The mismatch is dispatch/source ownership, not absence.
Finite main c772d47 already contains PR #307's qualified main-delivery proposals and
pins Foundation 0.5.1 at b72d5ab. The personal source is0.5.1 at 2d3230b; those
milestone versions do not establish identical runtime behavior. Both repositories
had no open PRs and Finite's merge queue was empty when inspected during planning.

The confirmed absent 1Password manifest paths do not alone prove all end-to-end
browser integration is broken: extension/app handshakes remain an explicit test.
Likewise the camera enumeration receipt is not a frame-capture or quality test.
