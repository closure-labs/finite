# Dell XPS 13 9350 Secure Boot status

The next images use Fedora's signed `7.2.0-61.fc45` kernel and its in-tree IPU7
camera drivers. Finite does not install modules under `updates/`, compile a
kernel module, or weaken module-signature enforcement. Secure Boot can remain
enabled under the normal Bluefin/Fedora trust model.

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

Every path must start with `/lib/modules/$release/kernel/`, every `intree` value
must be `Y`, and every signer must identify the Fedora kernel signing key.

## Verify runtime binding

```console
readlink -f /sys/bus/i2c/devices/i2c-INTC10DE:00/driver
readlink -f /sys/bus/i2c/devices/i2c-OVTI02C1:00/driver
cam -l
journalctl -k -b --no-pager | \
  rg -i 'ipu7|intel.cvs|ipu-bridge|ov02c10|module verification'
```

The expected camera path contains no HM1092 or external Finite module. Recheck
the release, provider paths, signatures, and capture after changing the pinned
kernel source lock.
