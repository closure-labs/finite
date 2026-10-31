#!/usr/bin/env python3
"""Exercise transient/permanent download outcomes with the real curl client."""
import contextlib
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
ACTION = ROOT / '.github/actions/setup-cosign'
PIN = 'sigstore/cosign-installer@6f9f17788090df1f26f669e9d70d6ae9567deba6'


class DownloadTests(unittest.TestCase):
    @contextlib.contextmanager
    def endpoint(self, statuses):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                status = statuses[min(len(requests), len(statuses) - 1)]
                requests.append(status)
                body = b'expected immutable executable' if status == 200 else b'transient gateway failure'
                self.send_response(status)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *_args):
                pass
        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01})
            worker.start()
            try:
                yield f'http://127.0.0.1:{server.server_port}/cosign', requests
            finally:
                server.shutdown()
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())

    def download(self, url, output, *options):
        # Production has a 15-second delay. Shorten only fixture delays while
        # using the real CURL_HOME discovery and upstream installer's flags.
        return subprocess.run(['curl', '--retry', '3', '-fsSL', '--retry-delay', '0',
                               *options, url, '-o', str(output)], cwd=output.parent,
                              env={**os.environ, 'CURL_HOME': str(ACTION / 'download'),
                                   'NO_PROXY': '*', 'no_proxy': '*'},
                              capture_output=True, timeout=25)

    def test_transient_gateway_recovers_without_repeating_failed_bytes(self):
        with tempfile.TemporaryDirectory() as directory, self.endpoint([504, 200]) as (url, requests):
            output = Path(directory) / 'cosign'
            result = self.download(url, output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(requests, [504, 200])
            self.assertEqual(output.read_bytes(), b'expected immutable executable')

    def test_rate_limit_is_transient(self):
        with tempfile.TemporaryDirectory() as directory, self.endpoint([429, 200]) as (url, requests):
            result = self.download(url, Path(directory) / 'cosign')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(requests, [429, 200])

    def test_permanent_errors_are_not_retried(self):
        for status in (401, 403, 404):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory, self.endpoint([status]) as (url, requests):
                result = self.download(url, Path(directory) / 'cosign')
                self.assertEqual(result.returncode, 22)
                self.assertEqual(requests, [status])

    def test_persistent_gateway_exhausts_exact_attempt_count(self):
        with tempfile.TemporaryDirectory() as directory, self.endpoint([504]) as (url, requests):
            result = self.download(url, Path(directory) / 'cosign')
            self.assertEqual(result.returncode, 22)
            self.assertEqual(requests, [504] * 4)

    def test_upstream_verification_is_preserved_and_configuration_is_scoped(self):
        action = yaml.safe_load((ACTION / 'action.yml').read_text())
        self.assertEqual(action['inputs']['cosign-release']['default'], 'v3.0.6')
        steps = action['runs']['steps']
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]['uses'], PIN)
        self.assertEqual(steps[0]['with'], {'cosign-release': '${{ inputs.cosign-release }}'})
        self.assertEqual(steps[0]['env'], {'CURL_HOME': '${{ github.action_path }}/download'})
        self.assertNotIn('continue-on-error', steps[0])
        settings = dict(line.split(' = ') for line in (ACTION / 'download/.curlrc').read_text().splitlines()
                        if line and not line.startswith('#'))
        self.assertEqual(settings, {'connect-timeout': '15', 'max-time': '60',
                                    'retry-delay': '15', 'retry-max-time': '180'})
        # The bundled exact-commit action works independently of sparse checkout.
        calls = []
        for path in (ROOT / '.github/workflows').glob('*.yml'):
            workflow = yaml.safe_load(path.read_text())
            for job_name, job in workflow.get('jobs', {}).items():
                for step in job.get('steps', []):
                    self.assertNotEqual(step.get('uses'), PIN)
                    if step.get('uses') == '$/.github/actions/setup-cosign':
                        calls.append((path.name, job_name, step))
                        self.assertNotIn('continue-on-error', step)
            self.assertNotIn('CURL_HOME', workflow.get('env', {}))
        # Include the experiment's isolated signature fixture. Check call sites,
        # not just a count that could hide a missing caller plus a duplicate.
        self.assertCountEqual([(path, job) for path, job, _step in calls], [
            ('bootability-pilot.yml', 'pilot'),
            ('containerfile-experiment.yml', 'signature-fixture'),
            ('desktop-security-evidence.yml', 'evidence'),
            ('iso.yml', 'iso'),
            ('publication.yml', 'sign'),
            ('qualification.yml', 'phase'),
            ('release-recovery.yml', 'sign-release'),
            ('release.yml', 'sign-release'),
            ('remediation-transaction.yml', 'transaction'),
            ('vm-acceptance.yml', 'vm'),
        ])
        fixture = next(step for path, _job, step in calls if path == 'containerfile-experiment.yml')
        self.assertEqual(fixture['with']['cosign-release'], 'v3.1.3')
        signer = next(step for path, _job, step in calls if path == 'publication.yml')
        self.assertEqual(signer['with']['cosign-release'], 'v3.1.3')

    def test_changed_download_policy_keeps_vm_coverage_without_os_payload_rebuild(self):
        import sys
        sys.path.insert(0, str(ROOT / 'scripts/ci'))
        import impact
        spec = importlib.util.spec_from_file_location('cosign_vm_selection', ROOT / 'scripts/ci/vm-selection.py')
        selector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(selector)
        for path in ('.github/actions/setup-cosign/action.yml', '.github/actions/setup-cosign/download/.curlrc'):
            with self.subTest(path=path):
                self.assertEqual(impact.classify([path]), {'checks': True, 'nix': False, 'profiles': []})
                self.assertTrue(selector.required([path]))


if __name__ == '__main__':
    unittest.main()
