# Dell XPS 13 9350 Secure Boot status

The two active images preserve their approved upstream Bluefin kernel and
modules. Secure Boot uses the upstream Bluefin/Fedora trust model. Check the
installed kernel and module signatures on the target hardware.

## Verify installed modules

```console
release=$(uname -r)
for module in intel_cvs ipu_bridge intel_ipu7 intel_ipu7_isys ov02c10; do
  path=$(modinfo -k "$release" -F filename "$module")
  printf '%s: %s\n' "$module" "$path"
  modinfo -k "$release" -F intree "$module"
  modinfo -k "$release" -F signer "$module"
done
```

Every module must belong to the running kernel release and retain its upstream
signature. In-tree camera drivers use `/lib/modules/$release/kernel/` and report
`intree` as `Y`; inspect additional upstream module providers separately.

## Verify runtime binding

```console
readlink -f /sys/bus/i2c/devices/i2c-INTC10DE:00/driver
readlink -f /sys/bus/i2c/devices/i2c-OVTI02C1:00/driver
cam -l
journalctl -k -b --no-pager | \
  rg -i 'ipu7|intel.cvs|ipu-bridge|ov02c10|module verification'
```

Recheck the release, provider paths, signatures and camera capture after
updating the approved upstream image.
