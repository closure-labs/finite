#!/usr/bin/env bash
# Root in a disposable pilot guest. Output contains only public boot facts.
set -euo pipefail
# SSH can precede multi-user.target; wait without probing Nix/HM/Brew.
for ((attempt=0; attempt<120; attempt++)); do
  if systemctl is-active --quiet local-fs.target && systemctl is-active --quiet multi-user.target; then break; fi
  if systemctl is-active --quiet emergency.target || systemctl is-active --quiet rescue.target; then exit 1; fi
  sleep 1
done
systemctl is-active --quiet local-fs.target
systemctl is-active --quiet multi-user.target
if systemctl is-active --quiet emergency.target || systemctl is-active --quiet rescue.target; then exit 1; fi
test -e /run/ostree-booted
python3 - <<'PY'
import json, os, pathlib, subprocess

def out(*args):
    return subprocess.check_output(args, text=True).strip()
status = json.loads(out('bootc', 'status', '--json'))['status']
booted = status['booted']
checksum = booted['ostree']['checksum']
args = out('cat', '/proc/cmdline').split()
def one(prefix):
    values = [a[len(prefix):] for a in args if a.startswith(prefix)]
    if len(values) != 1:
        raise ValueError('Missing/ambiguous required kernel argument: ' + prefix)
    return values[0]
ostree = one('ostree=')
assert ostree.startswith('/ostree/boot.')
deployment = pathlib.Path('/sysroot' + ostree).resolve(strict=True)
assert deployment.parent.name == 'deploy' and deployment.name.startswith(checksum + '.')
root = out('findmnt', '-n', '-o', 'SOURCE', '--target', '/sysroot').split('[')[0]
root_uuid = out('blkid', '-s', 'UUID', '-o', 'value', root)
assert one('root=') == 'UUID=' + root_uuid
luks_args = [a.split('=', 1)[1].removeprefix('luks-') for a in args if a.startswith('rd.luks.uuid=')]
assert luks_args
for path in ('/sysroot', '/var'):
    device = out('findmnt', '-n', '-o', 'SOURCE', '--target', path).split('[')[0]
    tree = json.loads(out('lsblk', '--inverse', '--json', '--output', 'NAME,TYPE', device))
    def walk(nodes):
        for node in nodes:
            yield node
            yield from walk(node.get('children', []))
    mappings = [n['name'] for n in walk(tree['blockdevices']) if n['type'] == 'crypt']
    assert mappings
    for mapping in mappings:
        crypt = out('cryptsetup', 'status', mapping)
        assert any(line.strip().startswith('type:') and line.split(':', 1)[1].strip() in ('LUKS1', 'LUKS2') for line in crypt.splitlines())
        backing = next(line.split(':', 1)[1].strip() for line in crypt.splitlines() if line.strip().startswith('device:'))
        assert out('blkid', '-s', 'UUID', '-o', 'value', backing) in luks_args
# Probe the current boot only, including initrd messages. Fail closed on errors.
journal = out('journalctl', '-b', '--no-pager', '-o', 'cat')
failures = ('Kernel panic - not syncing', 'Entering emergency mode', 'You are in emergency mode', 'Failed to switch root', 'Failed to mount /sysroot')
assert not any(message in journal for message in failures)
profile = json.loads(pathlib.Path('/usr/share/finite/profile.json').read_text())
assert out('uname', '-r') == profile['kernelRelease']
assert pathlib.Path('/usr/share/finite/build-profile').read_text().strip() == profile['profile']
print(json.dumps({'profile': profile['profile'], 'kernel': out('uname', '-r'),
    'bootId': pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
    'ostree': checksum, 'ostreeArgument': ostree, 'rootUuid': root_uuid,
    'localFs': True, 'multiUser': True, 'emergency': False,
    'encryptedRoot': True, 'encryptedVar': True, 'rootBinding': True, 'initramfsFailure': False}))
PY
