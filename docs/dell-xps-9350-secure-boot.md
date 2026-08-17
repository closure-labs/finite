# Dell XPS 13 9350 Secure Boot status

Last verified against the SVP7500 fix-pack integration: 2026-07-27.

The `dell-xps-9350-intel` profile builds out-of-tree camera modules from
`svp7500-camera-fix-pack`. Purplefin installs the current unsigned modules under
`/usr/lib/modules/$release/updates/purplefin`. Keep kernel module-signature
enforcement disabled for this profile.

## Module provider selection

The fix-pack's `docs/MAINLINE-CVS-EVALUATION.md` records the provider decision
for SVP7500 systems. Mainline `cvs` expects a node inside a firmware-described
media graph. This laptop uses CVS as a control-plane bridge for camera ownership
and MIPI configuration while the sensor connects directly to IPU7.

Purplefin therefore builds the pinned fix-pack `intel_cvs`, its patched
`ipu_bridge`, and HM1092 support against Bluefin's included kernel.

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
each module's vermagic must match `uname -r`. An empty signer confirms the
current unsigned-module policy.

The INT3472 provider is selected independently. On kernels whose in-tree
`intel_skl_int3472_discrete` already exposes `ir_flood`, Purplefin deliberately
keeps the in-tree driver because the fix-pack replacement would remove the LED
class device. The provider decision is recorded in `source-provenance`.

## Signature policy

- Keep Secure Boot and kernel lockdown enforcement disabled for the current
  unsigned `updates/purplefin` modules.
- Use Purplefin's selected `intel_cvs` and INT3472 providers.
- Build every module for the exact target kernel release.
- Verify module paths, vermagic, and provider choices after each kernel update.

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
bind normally, and the journal should show successful module loading.
