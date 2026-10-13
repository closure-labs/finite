#!/usr/bin/env python3
"""Execute the guest signature rejection boundary without a VM or registry."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class SignatureRejection(unittest.TestCase):
    def exercise(self, message, status):
        script = (ROOT / 'scripts/bluebuild/vm-acceptance.sh').read_text()
        section = script.split("echo 'Testing rejection with the wrong signing key'", 1)[1]
        invocation, rest = section.split("<<'GUEST'\n", 1)
        self.assertIn('>"$state/signature-rejection.log" 2>&1', invocation)
        guest = rest.split('\nGUEST', 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = root / 'policy.json'
            policy.write_text('original policy\n')
            public = root / 'wrong.pub'
            guest = guest.replace('/etc/containers/policy.json', str(policy)).replace(
                '/etc/pki/containers/finite-acceptance-wrong.pub', str(public))
            setup = '''
sudo() {
  case "$1" in
    chown|restorecon) return 0 ;;
    *) "$@" ;;
  esac
}
cosign() {
  printf private-fixture >"$3.key"
  printf public-fixture >"$3.pub"
}
jq() { printf 'wrong policy\\n'; }
bootc() {
  [[ $(cat "$FIXTURE_POLICY") == 'wrong policy' ]] || return 99
  printf '%s\\n' "$FIXTURE_MESSAGE" >&2
  return "$FIXTURE_STATUS"
}
'''
            env = dict(os.environ, TMPDIR=str(root), FIXTURE_POLICY=str(policy),
                       FIXTURE_MESSAGE=message, FIXTURE_STATUS=str(status))
            log = root / 'signature-rejection.log'
            with log.open('w') as output:
                result = subprocess.run(['bash', '-s', '--', 'candidate'], input=setup + guest,
                                        text=True, stdout=output, stderr=subprocess.STDOUT, env=env)
            retained = log.read_text()
            self.assertIn(message, retained)
            self.assertNotIn('private-fixture', retained)
            self.assertEqual(policy.read_text(), 'original policy\n')
            self.assertFalse(public.exists())
            self.assertEqual(sorted(path.name for path in root.iterdir()),
                             ['policy.json', 'signature-rejection.log'])
            return result.returncode

    def test_known_signature_failures_are_recognized(self):
        for message in ('invalid signature', 'no matching signatures',
                        'none of the signatures', 'signature verification failed',
                        'A signature was required, but no signature exists'):
            with self.subTest(message=message):
                self.assertEqual(self.exercise(message, 1), 0)

    def test_acceptance_is_failure_even_with_signature_error_text(self):
        self.assertNotEqual(self.exercise('invalid signature', 0), 0)

    def test_operational_errors_do_not_prove_signature_rejection(self):
        for message in ('network unavailable', 'unauthorized: authentication required',
                        'connection timed out', 'signature service unavailable'):
            with self.subTest(message=message):
                self.assertNotEqual(self.exercise(message, 1), 0)


if __name__ == '__main__':
    unittest.main()
