#!/usr/bin/env python3
"""Bind the running guest client and actual daemon ELF to image metadata."""
import hashlib
import json
import re
from pathlib import Path
import subprocess

manifest = json.loads(Path('/usr/lib/finite/nix-runtime/runtime.json').read_text())
runtime, library = Path(manifest['runtime']), Path(manifest['library'])
digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
binary = runtime/'bin/nix'
assert digest(binary) == manifest['binarySha256']
assert digest(library) == manifest['librarySha256']
for path in (binary, library):
    expected = subprocess.check_output(['matchpathcon', '-n', str(path)], text=True).strip().split(':')[2]
    actual = subprocess.check_output(['stat', '-c', '%C', str(path)], text=True).strip().split(':')[2]
    assert actual == expected and actual not in ('default_t', 'unlabeled_t'), 'Native runtime SELinux label mismatch'
assert Path('/nix/var/nix/profiles/default/bin/nix').resolve() == binary
subprocess.run([str(binary), '--extra-experimental-features', 'nix-command', '--store', 'daemon',
                'store', 'ping'], check=True, capture_output=True, timeout=30)
group = subprocess.check_output(['systemctl', 'show', '--property=ControlGroup', '--value',
                                 'nix-daemon.service'], text=True).strip()
assert group.startswith('/system.slice/') and '..' not in group
pids = (Path('/sys/fs/cgroup')/group.lstrip('/')/'cgroup.procs').read_text().split()
matched = []
for pid in pids:
    assert pid.isdecimal()
    try:
        process = Path('/proc')/pid
        if (process/'exe').resolve() != binary:
            continue
        assert str(library) in (process/'maps').read_text()
        assert digest(process/'exe') == manifest['binarySha256']
        matched.append(pid)
    except FileNotFoundError:
        continue
assert matched, 'No running fixed Nix daemon found in its service cgroup'
journal = subprocess.check_output(['journalctl', '-b', '-u', 'finite-nix-runtime.service',
                                    '--output=cat', '--no-pager'], text=True)
prior = [line.removeprefix('Prior native Nix: ') for line in journal.splitlines()
         if line.startswith('Prior native Nix: ')]
assert len(prior) == 1
marker = Path('/var/home/nix/finite-predecessor-fixture')
if marker.exists():
    assert re.fullmatch(r'sha256:[0-9a-f]{64}\n?', marker.read_text())
    # On the first boot this fixture must replace the real predecessor client.
    # Subsequent boots must select the same fixed runtime without reinstalling.
    if not Path('/var/lib/finite-vm/native-nix-verified').exists():
        assert prior[0] != str(binary)
    else:
        assert prior[0] == str(binary)
Path('/var/lib/finite-vm/native-nix-verified').touch()
print(json.dumps({'schema': 1, 'status': 'pass', 'client': str(binary),
    'binarySha256': manifest['binarySha256'], 'librarySha256': manifest['librarySha256'],
    'runningDaemonMatched': True, 'predecessorStatePresent': marker.exists(),
    'selinuxTypesMatched': True,
    'priorClient': prior[0], 'sourceRevision': manifest['sourceRevision'],
    'patchedSourceSha256': manifest['patchedSourceSha256']}))
