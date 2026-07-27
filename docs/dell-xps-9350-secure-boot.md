# Dell XPS 13 9350 Secure Boot status

Last verified against the SVP7500 fix-pack integration: 2026-07-27.

The `dell-xps-9350-intel` profile builds out-of-tree camera modules from
`svp7500-camera-fix-pack`. They are installed under
`/usr/lib/modules/$release/updates/purplefin` and are not signed by Purplefin.
Do not enable kernel module-signature enforcement for this profile unless those
exact modules are signed with a key trusted by the booted kernel.

## Why there is no in-tree handoff

The fix-pack's `docs/MAINLINE-CVS-EVALUATION.md` demonstrates that mainline
`cvs` is not a replacement for the external `intel_cvs` on SVP7500 systems.
Mainline expects CVS to be a node inside a firmware-described media graph. On
this laptop it is a control-plane-only bridge for camera ownership and MIPI
configuration, while the sensor connects directly to IPU7 in the media graph.

Consequently, a kernel version such as 7.2 is not a Secure Boot migration
boundary. Purplefin always uses the pinned fix-pack `intel_cvs`, plus its
patched `ipu_bridge` and HM1092 support, against Bluefin's included kernel.

## Inspect the installed stack

Run:

```bash
uname -r
cat /usr/share/purplefin/dell-ipu7/source-provenance

for module in intel_cvs ipu_bridge hm1092; do
  modinfo -n "$module"
  modinfo -F vermagic "$module"
  modinfo -F signer "$module"
done
```

Expected paths contain `updates/purplefin`. The recorded kernel release and
each module's vermagic must match `uname -r`. An empty signer means the module
is unsigned.

The INT3472 provider is selected independently. On kernels whose in-tree
`intel_skl_int3472_discrete` already exposes `ir_flood`, Purplefin deliberately
keeps the in-tree driver because the fix-pack replacement would remove the LED
class device. The provider decision is recorded in `source-provenance`.

## Safe policy

- Keep Secure Boot or kernel lockdown enforcement disabled while the
  `updates/purplefin` modules are unsigned.
- Do not switch to mainline `cvs` merely because a newer kernel contains it.
- Do not copy a module between kernel trees; rebuild and sign it for the exact
  target release.
- Do not install the fix-pack's INT3472 replacement over a kernel that already
  exposes the IR flood LED.

To support enforced signatures in the future, add a reproducible image-build
signing step for every installed fix-pack module, enroll the corresponding
certificate through the normal Bluefin MOK procedure, and verify the signer
and vermagic before enabling enforcement. That signing workflow is not
implemented by the current profile.

## Runtime verification

With signature enforcement in its intended state, verify normal binding and
camera behavior:

```bash
readlink -f /sys/bus/i2c/devices/i2c-INTC10DE:00/driver
readlink -f /sys/bus/i2c/devices/i2c-OVTI02C1:00/driver
cam -l
journalctl -k -b --no-pager |
  rg -i 'ipu7|intel.cvs|ipu-bridge|hm1092|ov02c10|module verification'
```

The bridge should bind to the fix-pack's `Intel CVS driver`, OV02C10 should
bind normally, and the journal must not contain a module-verification failure.
