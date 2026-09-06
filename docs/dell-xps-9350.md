# Dell XPS 13 9350

Choose `next` for Bluefin or `dev-next` for Bluefin DX on the XPS 13 9350.
Both provide the pinned Fedora kernel `7.2.0-61.fc45.x86_64`. Follow the
[installation and update guide](installation.md) to select the signed channel
and retain the previous deployment. Check the running kernel with `uname -r`.

## Optional Home Manager display policy

At first login, Finite recognizes the Dell/XPS DMI identity and selects the
`dell-xps-9350-intel` Home Manager aspect. The user environment applies this internal-panel policy:

- `1920x1200@120.000+vrr` on AC;
- `1920x1200@60.000` on battery;
- automatic GNOME ambient brightness setup.

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
capture on this hardware. WebRTC uses the libcamera source exposed by WirePlumber.

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
`about:config`. Home Manager supplies this setting through the Firefox package policy.

Module paths must be below the running release's `kernel/` directory, `intree`
must be `Y`, and the signer must be the Fedora kernel signing key. See
[Secure Boot status](dell-xps-9350-secure-boot.md) for the trust contract.
