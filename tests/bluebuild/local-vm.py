#!/usr/bin/env python3
"""Exercise local candidate export/installer wiring without network or credentials."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MOCK = '''#!PYTHON
import hashlib, io, json, os, pathlib, sys, tarfile
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
if name == 'sudo':
    os.execvp(args[0], args)
if name == 'docker':
    if args[0] == 'pull':
        assert args[1] == 'ghcr.io/closure-labs/finite@sha256:' + 'c'*64
    elif args[0] == 'create':
        assert '--network=none' in args
        print('fixture-container')
    elif args[0] == 'cp':
        assert args[1] == 'fixture-container:/usr/lib/finite/determinate-nix-seed'
        assert args[2] == '-'
        with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as archive:
            for name in ('determinate-nix-seed','determinate-nix-seed/store','determinate-nix-seed/var/nix/db'):
                entry=tarfile.TarInfo(name);entry.type=tarfile.DIRTYPE;archive.addfile(entry)
            entry=tarfile.TarInfo('determinate-nix-seed/receipt.json');entry.size=2;archive.addfile(entry,io.BytesIO(b'{}'))
    elif args[0] == 'rm':
        assert args[1] == 'fixture-container'
    elif args[0] == 'inspect':
        assert args == ['inspect', '--format', '{{.Id}}', 'a' * 12]
        print('sha256:' + 'a' * 64)
    elif args[0] == 'tag':
        assert args[1] == 'sha256:' + 'a' * 64
    elif args[0] == 'run' and '--entrypoint' in args:
        print('44')
    else:
        assert 'IMAGE_SIGNED=false' in args
        assert any(arg.startswith('IMAGE_SRC=oci-archive:') for arg in args)
        output = next(arg.split(':')[0] for arg in args if arg.endswith(':/build-container-installer/build'))
        pathlib.Path(output, 'finite.iso').write_bytes(b'local installer')
    assert '--push' not in args
elif name == 'skopeo':
    if args[0] == 'copy':
        assert args[1:3] == ['--format', 'oci']
        assert args[-2].startswith('docker-daemon:localhost/finite-validation:')
        assert args[-1].startswith('oci-archive:')
        assert not any(arg.startswith('docker://') for arg in args)
    elif '--format' in args:
        print('sha256:'+'c'*64)
    else:
        print(json.dumps({'schemaVersion': 2, 'config': {'digest': 'sha256:' + 'b' * 64}}))
elif name == 'cosign':
    assert args == ['verify','--new-bundle-format=false','--key','cosign.pub','ghcr.io/closure-labs/finite@sha256:'+'c'*64]
    print('[]')
'''


class LocalVM(unittest.TestCase):
    def test_export_is_local_and_vm_receipt_is_diagnostic_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'bin').mkdir()
            for name in ('docker', 'skopeo', 'sudo', 'cosign'):
                tool = root / 'bin' / name
                tool.write_text(MOCK.replace('PYTHON', sys.executable, 1))
                tool.chmod(0o755)
            (root / 'scripts/bluebuild').mkdir(parents=True)
            (root / 'scripts/ci').mkdir(parents=True)
            (root / 'scripts/ci/native-nix-selection.py').write_text('print("true")\n')
            shutil.copy(ROOT / 'scripts/bluebuild/local-vm.sh', root / 'scripts/bluebuild/local-vm.sh')
            shutil.copy(ROOT / 'scripts/bluebuild/measure.py', root / 'scripts/bluebuild/measure.py')
            (root / 'scripts/bluebuild/prepare-installer.sh').write_text('''#!/usr/bin/env bash
set -eu
mkdir -p "$ISO_OUTPUT_DIR"
printf '{}\\n' >"$ISO_OUTPUT_DIR/installer.json"
''')
            (root / 'scripts/bluebuild/vm-acceptance.sh').write_text('''#!/usr/bin/env bash
set -eu
[[ $FINITE_LOCAL_VM_VALIDATION == true && $FINITE_SECURE_BOOT == true && -z $2 && $3 == fresh ]]
(cd "$1" && sha256sum -c SHA256SUMS)
cp "$1/installation.json" result.json
mkdir -p .bluebuild/vm-local
if [[ -n ${FINITE_NATIVE_NIX_PREDECESSOR:-} ]]; then
  test -s "$FINITE_NATIVE_NIX_PREDECESSOR/state.tar"
  test -s "$FINITE_NATIVE_NIX_PREDECESSOR/provenance.json"
fi
''')
            (root / 'sources').mkdir()
            (root / 'sources/bluebuild-installer.json').write_text('{"cliAlias":"installer-fixture"}')
            (root / '.bluebuild').mkdir()
            (root / '.bluebuild/finite-image-ref.txt').write_text('a' * 12)
            env = {**os.environ, 'PATH': str(root / 'bin') + ':' + os.environ['PATH'],
                   'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite',
                   'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_REF': 'refs/pull/5/merge',
                   'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '5', 'GITHUB_RUN_ATTEMPT': '1'}
            result = subprocess.run(['bash', 'scripts/bluebuild/local-vm.sh', 'finite'], cwd=root,
                                    env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            document = json.loads((root / 'result.json').read_text())
            self.assertTrue(document['localValidation'])
            self.assertTrue(document['image'].startswith('local-image@sha256:'))
            self.assertEqual(document['sourceRevision'], 'a' * 40)
            self.assertFalse(list((root / '.bluebuild').glob('*.iso')))
            timings = [json.loads(line) for line in (root / '.bluebuild/finite-timings.jsonl').read_text().splitlines()]
            self.assertEqual([entry['stage'] for entry in timings], [
                'local-vm-oci-export', 'local-vm-installer-prepare', 'local-vm-iso-build', 'local-vm-acceptance', 'local-vm-persistent-nix'])
            self.assertTrue((root/'.bluebuild/vm-local-fresh').is_dir())
            self.assertTrue((root/'.bluebuild/vm-local-persistent-nix').is_dir())
            for entry in timings:
                self.assertEqual(entry['repository'], 'closure-labs/finite')
                self.assertEqual(entry['runId'], '5')
                self.assertEqual(entry['runAttempt'], '1')
                self.assertEqual(entry['revision'], 'a' * 40)
                self.assertEqual(entry['profile'], 'finite')
                self.assertEqual(entry['status'], 0)
                self.assertFalse(entry['authorizesPublication'])
            self.assertIsNone(timings[0]['candidateDigest'])
            self.assertTrue(all(entry['candidateDigest'] == document['image'].split('@')[1]
                                for entry in timings[1:]))


if __name__ == '__main__':
    unittest.main()
