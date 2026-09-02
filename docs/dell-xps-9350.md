# Dell XPS 13 9350

Use `next` or `dev-next` on the XPS 13 9350. These are
vendor-neutral images: their only hardware delta from the corresponding generic
image is the pinned Fedora 7.2 runtime kernel.

```console
sudo bootc switch ghcr.io/closure-labs/finite:dev-next
sudo systemctl reboot
uname -r
```

The expected kernel release is `7.2.0-61.fc45.x86_64`. The image does not ship
an XPS rootfs overlay, external modules, a custom libcamera build, camera udev
rules, PAM changes, charging policy, TuneD profile, or rEFInd theme.

## Optional Home Manager display policy

At first login, Finite recognizes the Dell/XPS DMI identity and selects the
`dell-xps-9350-intel` Home Manager aspect. This is separate from the image's
`next-x86_64` identity. The aspect preserves the internal-panel policy:

- `1920x1200@120.000+vrr` on AC;
- `1920x1200@60.000` on battery;
- a one-time migration that enables GNOME ambient brightness.

The policy verifies the DMI identity before changing the display and leaves
external or complex monitor layouts alone. Its configuration is local to the
user:

```console
$EDITOR ~/.config/finite/dell-xps-9350-panel.conf
systemctl --user restart finite-dell-xps-9350-panel.service
systemctl --user status finite-dell-xps-9350-panel.service
gdctl show --modes --properties
```

Home Manager configures Finite's Nix Firefox package to use PipeWire for camera
capture on this hardware. This package-level preference leaves existing
Firefox profiles intact and makes WebRTC consume WirePlumber's usable libcamera
source instead of the raw IPU7 V4L2 capture endpoints.

## IPU7 camera

Fedora 7.2 supplies the CVS bridge, IPU bridge, IPU7, IPU7 ISYS, and OV02C10
sensor drivers in-tree. Verify the installed provider and camera graph with:

```console
uname -r
for module in intel_cvs ipu_bridge intel_ipu7 intel_ipu7_isys ov02c10; do
  modinfo -n "$module"
  modinfo -F intree "$module"
  modinfo -F signer "$module"
done
journalctl -k -b | rg -i 'ipu7|intel.cvs|ipu-bridge|ov02c10|camera'
cam -l
wpctl status
```

In Firefox, `media.webrtc.camera.allow-pipewire` must be `true` in
`about:config`. The setting is supplied by the Home Manager package policy; it
does not require a profile-specific `user.js` or a user service.

Module paths must be below the running release's `kernel/` directory, `intree`
must be `Y`, and the signer must be the Fedora kernel signing key. See
[Secure Boot status](dell-xps-9350-secure-boot.md) for the trust contract.
