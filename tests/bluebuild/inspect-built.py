#!/usr/bin/env python3
"""Exercise candidate pull retries and the verification boundary without a registry."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/bluebuild/inspect-built.sh'
DIGEST = 'sha256:' + 'a' * 64
IMAGE = 'ghcr.io/closure-labs/finite@' + DIGEST
MOCK = '''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open('calls.jsonl', 'a') as log:
    log.write(json.dumps([name, *args]) + '\\n')
if name == 'timeout':
    sys.exit(subprocess.call(args[1:]))
elif name == 'skopeo':
    print(json.dumps({'Digest': os.environ['DIGEST']}))
elif name == 'docker':
    if args[0] == 'pull':
        state = pathlib.Path('pull-attempts')
        attempt = int(state.read_text()) if state.exists() else 0
        state.write_text(str(attempt + 1))
        statuses = json.loads(os.environ['PULL_STATUSES'])
        sys.exit(statuses[min(attempt, len(statuses) - 1)])
    elif args[0] == 'inspect':
        print(json.dumps([{'Config': {'Labels': {
            'org.opencontainers.image.revision': 'local',
            'org.opencontainers.image.base.digest': os.environ['DIGEST'],
            'io.finite.profile': 'bluefin-dx-generic',
            'org.opencontainers.image.source': 'https://github.com/closure-labs/finite',
        }}}]))
elif name == 'cosign':
    sys.exit(int(os.environ.get('SIGNATURE_STATUS', '0')))
'''


class CandidatePull(unittest.TestCase):
    def run_inspection(self, statuses, signature_status=0):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        bindir = root / 'bin'
        bindir.mkdir()
        for name in ['timeout', 'sleep', 'skopeo', 'docker', 'cosign']:
            tool = bindir / name
            tool.write_text(MOCK.replace('#!/usr/bin/env python3', '#!' + sys.executable, 1))
            tool.chmod(0o755)
        (root / '.bluebuild').mkdir()
        (root / '.bluebuild/bluefin-dx-generic-publication.json').write_text(json.dumps({
            'profile': 'bluefin-dx-generic', 'tags': ['finite-dev'],
            'digest': DIGEST, 'candidate': 'candidate-test',
        }))
        (root / 'sources').mkdir()
        (root / 'sources/kernel-next.json').write_text(json.dumps({'release': 'test'}))
        env = dict(os.environ, PATH=str(bindir) + ':' + os.environ['PATH'],
                   DIGEST=DIGEST, PULL_STATUSES=json.dumps(statuses),
                   SIGNATURE_STATUS=str(signature_status), GITHUB_SHA='local')
        result = subprocess.run(
            ['bash', str(SCRIPT), 'bluefin-dx-generic', 'finite-dev', 'true'],
            cwd=root, env=env, capture_output=True, text=True, timeout=10,
        )
        calls = [json.loads(line) for line in (root / 'calls.jsonl').read_text().splitlines()]
        return root, result, calls

    def test_success_does_not_retry(self):
        root, result, calls = self.run_inspection([0])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c for c in calls if c[:2] == ['docker', 'pull']],
                         [['docker', 'pull', IMAGE]])
        self.assertFalse(any(c[0] == 'sleep' for c in calls))
        self.assertEqual((root / '.bluebuild/bluefin-dx-generic-image-ref.txt').read_text(), IMAGE + '\n')

    def test_timeout_and_transient_failure_retry_the_same_digest(self):
        _, result, calls = self.run_inspection([124, 1, 0])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c for c in calls if c[:3] == ['timeout', '15m', 'docker']],
                         [['timeout', '15m', 'docker', 'pull', IMAGE]] * 3)
        self.assertEqual([c for c in calls if c[0] == 'sleep'], [['sleep', '10']] * 2)
        self.assertEqual(sum(c[0] == 'skopeo' for c in calls), 1)
        self.assertIn('timed out after 15m', result.stderr)
        self.assertIn('failed with exit code 1', result.stderr)
        verification = next(i for i, c in enumerate(calls) if c[0] == 'cosign')
        last_pull = max(i for i, c in enumerate(calls) if c[:2] == ['docker', 'pull'])
        self.assertGreater(verification, last_pull)

    def test_exhausted_retries_stop_before_verification(self):
        for status in [124, 1]:
            with self.subTest(status=status):
                root, result, calls = self.run_inspection([status])
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertEqual(sum(c[:2] == ['docker', 'pull'] for c in calls), 3)
                self.assertEqual(sum(c[0] == 'sleep' for c in calls), 2)
                self.assertFalse(any(c[0] == 'cosign' or c[:2] in [
                    ['docker', 'inspect'], ['docker', 'run']] for c in calls))
                self.assertFalse((root / '.bluebuild/bluefin-dx-generic-image-ref.txt').exists())
                self.assertIn('verification cannot continue', result.stderr)

    def test_signature_failure_after_recovery_still_stops_verification(self):
        root, result, calls = self.run_inspection([124, 0], signature_status=1)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(any(c[:2] == ['docker', 'run'] for c in calls))
        self.assertFalse((root / '.bluebuild/bluefin-dx-generic-image-ref.txt').exists())


if __name__ == '__main__':
    unittest.main()
