# Dell XPS 13 9350 Secure Boot status

The `dell-xps-9350-intel` image installs unsigned out-of-tree camera modules
from the pinned SVP7500 fix pack. Keep Secure Boot and kernel module-signature
enforcement disabled for this profile.

Purplefin selects the fix pack's `intel_cvs`, patched `ipu_bridge`, and HM1092
modules. It keeps the in-tree INT3472 driver when that driver exposes the IR
flood LED interface.

## Verify installed modules

```bash
uname -r
cat /usr/share/purplefin/dell-ipu7/source-provenance

for module in intel_cvs ipu_bridge hm1092; do
  modinfo -n "$module"
  modinfo -F vermagic "$module"
  modinfo -F signer "$module"
done
```

Expected module paths contain `updates/purplefin`. The recorded kernel release
and each module's vermagic must match `uname -r`; the signer is empty.

## Verify runtime binding

```bash
readlink -f /sys/bus/i2c/devices/i2c-INTC10DE:00/driver
readlink -f /sys/bus/i2c/devices/i2c-OVTI02C1:00/driver
cam -l
journalctl -k -b --no-pager | \
  rg -i 'ipu7|intel.cvs|ipu-bridge|hm1092|ov02c10|module verification'
```

Recheck paths, vermagic, provider selection, and camera operation after every
kernel update.
