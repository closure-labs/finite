#!/usr/bin/env python3
"""False-success contracts for diagnostic-only boot evidence."""
import copy
import importlib.util
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('pilot', ROOT / 'scripts/bluebuild/bootability-pilot.py')
pilot = importlib.util.module_from_spec(spec); spec.loader.exec_module(pilot)

def good():
    source = 'ghcr.io/closure-labs/finite@sha256:' + 'a' * 64
    target = 'ghcr.io/closure-labs/finite@sha256:' + 'b' * 64
    guest = {'profile': 'finite', 'kernel': '6.19-test', 'bootId': '12345678-1234-1234-1234-123456789abc',
        'ostree': 'c' * 64, 'ostreeArgument': '/ostree/boot.1/default/hash/0', 'rootUuid': 'root-uuid',
        'localFs': True, 'multiUser': True, 'emergency': False, 'encryptedRoot': True, 'encryptedVar': True,
        'rootBinding': True, 'initramfsFailure': False}
    deployment = {'image': target, 'digest': 'sha256:' + 'b' * 64, 'ostree': 'd' * 64}
    return {'schema': 1, 'kind': 'finite-bootability-pilot', 'authorizesPublication': False,
        'validationOnly': True, 'head': 'e' * 40, 'runId': '123', 'runAttempt': 1,
        'source': source, 'candidate': target,
        'expected': {'profile': 'finite', 'kernel': '6.19-test', 'digests': ['sha256:' + 'b' * 64],
                     'identity': 'v1:' + 'e' * 64, 'revision': 'e' * 40},
        'first': guest, 'updated': {**guest, 'ostree': 'd' * 64, 'bootId': '87654321-1234-1234-1234-123456789abc'},
        'staged': deployment, 'booted': dict(deployment), 'secureBoot': True,
        'mokCertificateSha256': 'f' * 64, 'firmwareSha256': {k: 'a' * 64 for k in ('code', 'template', 'prepared')}, 'status': 'pass'}

class Receipt(unittest.TestCase):
    def test_success_and_all_false_success_mutations(self):
        pilot.validate(good())
        mutations = [
            ('old-deployment fallback', lambda v: v.update(updated=dict(v['first']))),
            ('wrong digest', lambda v: v['booted'].update(digest='sha256:' + 'a' * 64)),
            ('wrong kernel', lambda v: v['updated'].update(kernel='old-kernel')),
            ('wrong profile', lambda v: v['updated'].update(profile='finite-dev')),
            ('staged only', lambda v: v['booted'].update(image=v['source'], ostree=v['first']['ostree'])),
            ('emergency userspace', lambda v: v['updated'].update(emergency=True)),
            ('missing encrypted root', lambda v: v['updated'].update(encryptedRoot=False)),
            ('missing encrypted var', lambda v: v['updated'].update(encryptedVar=False)),
            ('initramfs failure', lambda v: v['updated'].update(initramfsFailure=True)),
            ('no multi-user', lambda v: v['updated'].update(multiUser=False)),
            ('no local-fs', lambda v: v['updated'].update(localFs=False)),
            ('wrong root', lambda v: v['updated'].update(rootUuid='other')),
            ('no root binding', lambda v: v['updated'].update(rootBinding=False)),
            ('secure boot disabled', lambda v: v.update(secureBoot=False)),
            ('promotion claim', lambda v: v.update(authorizesPublication=True)),
            ('same candidate', lambda v: v.update(source=v['candidate'])),
            ('incomplete', lambda v: v.pop('staged')),
            ('malformed truthy', lambda v: v['updated'].update(multiUser='true')),
        ]
        for name, mutate in mutations:
            with self.subTest(name=name):
                value = copy.deepcopy(good()); mutate(value)
                with self.assertRaises((ValueError, TypeError)): pilot.validate(value)
        for key in good():
            with self.subTest(missing=key):
                value = good(); del value[key]
                with self.assertRaises(ValueError): pilot.validate(value)

    def test_duplicate_and_malformed_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'receipt.json'
            for text in ('{', '{"schema":1,"schema":1}', 'x' * (1024 * 1024 + 1)):
                path.write_text(text)
                with self.assertRaises(ValueError): pilot.load(path)

    def test_index_only_allows_amd64_linux_platform(self):
        manifest = {'manifests': [{'digest': 'sha256:' + 'c' * 64, 'platform': {'os': 'linux', 'architecture': 'amd64'}},
                                  {'digest': 'sha256:' + 'd' * 64, 'platform': {'os': 'linux', 'architecture': 'arm64'}}]}
        self.assertEqual(pilot.manifest_digests(manifest, good()['candidate']), {'sha256:' + 'b' * 64, 'sha256:' + 'c' * 64})

    def test_manual_branch_first_attempt_only(self):
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite',
            'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/pilot',
            'GITHUB_WORKFLOW_REF': 'closure-labs/finite/.github/workflows/bootability-pilot.yml@refs/heads/pilot',
            'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': 'a' * 40}
        pilot.preflight(env)
        for key, value in [('GITHUB_REF', 'refs/heads/main'), ('GITHUB_RUN_ATTEMPT', '2'),
                           ('GITHUB_EVENT_NAME', 'pull_request'), ('GITHUB_REPOSITORY', 'other/repo')]:
            with self.assertRaises(ValueError): pilot.preflight({**env, key: value})

    def test_guest_requires_both_readiness_targets(self):
        script = (ROOT / 'scripts/bluebuild/check-bootability-guest.sh').read_text().replace('attempt<120', 'attempt<1')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            fake = path / 'systemctl'
            fake.write_text('#!/bin/bash\n[[ $* == "is-active --quiet local-fs.target" ]]\n')
            fake.chmod(0o755)
            sleep = path / 'sleep'; sleep.write_text('#!/bin/bash\nexit 0\n'); sleep.chmod(0o755)
            result = subprocess.run(['bash', '-s'], input=script, text=True, capture_output=True,
                env={**os.environ, 'PATH': str(path) + ':' + os.environ['PATH']})
            self.assertNotEqual(result.returncode, 0, 'local-fs alone must never imply multi-user readiness')

    def test_production_aggregator_rejects_pilot_receipt(self):
        spec = importlib.util.spec_from_file_location('qualification', ROOT / 'scripts/bluebuild/qualification-context.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'vm-fresh').mkdir()
            (root / 'vm-fresh/acceptance.json').write_text(json.dumps(good()))
            with self.assertRaisesRegex(ValueError, 'Required VM phase'):
                module.aggregate(root, 'finite', good()['candidate'], '', 'source', 'identity', 'head')

    def test_shared_helper_default_and_artifact_boundary(self):
        script = (ROOT / 'scripts/bluebuild/vm-acceptance.sh').read_text()
        self.assertIn('pilot=${FINITE_BOOTABILITY_PILOT:-false}', script)
        pilot_branch = script.split('begin_stage signed-update', 1)[1].split('activation_started=', 1)[0]
        self.assertNotIn('home-init', pilot_branch)
        self.assertNotIn('rollback', pilot_branch)
        self.assertIn('--enforce-container-sigpolicy', (ROOT / 'scripts/bluebuild/vm-upgrade.py').read_text())
        workflow = (ROOT / '.github/workflows/bootability-pilot.yml').read_text()
        artifact = workflow.split('name: Retain only allowlisted diagnostic receipts', 1)[1]
        self.assertNotIn('*.log', artifact)
        self.assertNotIn('*.qcow2', artifact)
        self.assertIn('timeout-minutes: 120', workflow)

if __name__ == '__main__': unittest.main()
