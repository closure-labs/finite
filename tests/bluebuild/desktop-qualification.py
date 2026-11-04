#!/usr/bin/env python3
"""Offline evidence binding and negative VM observation fixtures."""
import copy
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('desktop_test', ROOT / 'scripts/bluebuild/desktop-qualification.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Desktop(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = '{"schemaVersion":2,"manifests":[{"digest":"sha256:' + 'b' * 64 + '"}]}'
        self.image = 'ghcr.io/closure-labs/finite@sha256:' + hashlib.sha256(self.manifest.encode()).hexdigest()
        self.acceptance = dict(candidate=self.image, profile='finite', sourceRevision='c'*40,
                               buildIdentity='v1:'+'d'*64, previousDigest='')
        self.observation = m.guest.observations('Enforcing', '1', '',
            'system_u:system_r:init_t:s0 1 systemd\nsystem_u:system_r:sshd_t:s0 22 sshd',
            'tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=22,fd=3))', 'finite')
        self.write_phase('fresh', 'first-boot', 'source')

    def write_phase(self, phase, boot, manifest):
        base = self.root / ('vm-' + phase)
        base.mkdir()
        (base / (manifest+'-manifest.json')).write_text(self.manifest)
        (base / (boot+'.json')).write_text(json.dumps({'status': {'booted': {'image': {'imageDigest': 'sha256:'+'b'*64}}}}))
        (base / (boot+'-desktop.json')).write_text(json.dumps(self.observation))

    def test_fresh_and_upgrade(self):
        for upgrade in (False, True):
            if upgrade:
                self.acceptance['previousDigest'] = 'sha256:'+'e'*64
                self.write_phase('upgrade', 'updated', 'target')
            m.assemble(self.root, self.acceptance)
            path = m.verify(self.root, self.acceptance)
            receipt = json.loads(path.read_text())
            self.assertEqual(len(receipt['phases']), 2 if upgrade else 1)
            self.assertEqual(receipt['phases']['fresh']['observations']['desktop']['hardware'], 'not-assessed')

    def test_missing_upgrade_fails(self):
        self.acceptance['previousDigest'] = 'sha256:'+'e'*64
        with self.assertRaises(ValueError): m.assemble(self.root, self.acceptance)

    def test_binding_mutations_fail(self):
        m.assemble(self.root, self.acceptance)
        for key in ('candidate', 'profile', 'sourceRevision', 'buildIdentity'):
            bad = {**self.acceptance, key: 'wrong'}
            with self.subTest(key=key), self.assertRaises(ValueError): m.verify(self.root, bad)

    def test_tampering_missing_symlink_and_oversize_fail(self):
        m.assemble(self.root, self.acceptance)
        path = m.verify(self.root, self.acceptance)
        original = path.read_bytes()
        path.write_bytes(original+b' ')
        with self.assertRaises(ValueError): m.verify(self.root, self.acceptance)
        path.unlink()
        with self.assertRaises(ValueError): m.verify(self.root, self.acceptance)
        target = self.root/'target'; target.write_bytes(original); path.symlink_to(target)
        with self.assertRaises(ValueError): m.verify(self.root, self.acceptance)
        path.unlink(); path.write_bytes(b'x'*(m.LIMIT+1))
        with self.assertRaises(ValueError): m.verify(self.root, self.acceptance)

    def test_boot_manifest_checks_and_observation_truth(self):
        m.assemble(self.root, self.acceptance)
        receipt = json.loads(m.verify(self.root, self.acceptance).read_text())
        for mutate in (
            lambda r: r['phases']['fresh'].update(bootedDigest='sha256:'+'f'*64),
            lambda r: r['phases']['fresh'].update(manifest='{}'),
            lambda r: r['phases']['fresh']['observations']['checks'].update(selinuxEnforcing=False),
            lambda r: r['phases']['fresh']['observations']['selinux'].update(mode='Permissive'),
            lambda r: r['phases']['fresh']['observations'].update(listeners=[]),
            lambda r: r['phases']['fresh']['observations'].update(processes=[])):
            bad = copy.deepcopy(receipt); mutate(bad)
            with self.assertRaises(ValueError): m.validate(bad, self.acceptance)

    def test_permissive_inventory_not_blanket_waiver(self):
        args = ('Enforcing','1','unconfined_service_t',
                'system_u:system_r:init_t:s0 1 systemd\nsystem_u:system_r:sshd_t:s0 22 sshd',
                'tcp LISTEN 0 128 *:22 *:* owners', 'finite')
        observed=m.guest.observations(*args)
        self.assertEqual(observed['selinux']['permissiveDomains'], ['unconfined_service_t'])
        with self.assertRaises(ValueError): m.guest.observations(*(*args[:2], 'sshd_t', *args[3:]))

    def test_invalid_process_rows_still_fail_with_bounded_evidence(self):
        good = 'system_u:system_r:init_t:s0 1 systemd'
        for bad in ('?', '? 23 worker', 'system_u:system_r:init_t:s0 nope systemd',
                    'system_u:system_r:init_t:s0 ٢ systemd',
                    'system_u:system_r:init_t:s0 23', '?' * 1024):
            with self.subTest(row=bad[:40]), self.assertRaises(m.guest.ProcessObservationError) as caught:
                m.guest.observations('Enforcing', '1', '', good + '\n' + bad,
                                     'tcp LISTEN 0 128 *:22 *:* owners', 'finite')
            details = caught.exception.details
            self.assertEqual(details['stage'], 'processes')
            self.assertEqual(details['rowNumber'], 2)
            self.assertEqual(details['row'], bad[:m.guest.ERROR_ROW_LIMIT])
            self.assertEqual(details['rowLength'], len(bad))
            self.assertEqual(details['truncated'], len(bad) > m.guest.ERROR_ROW_LIMIT)
            self.assertIsInstance(caught.exception, ValueError)

    def test_collector_retains_error_details_and_returns_failure(self):
        values = ['Enforcing', '', '? 23 worker', 'tcp LISTEN 0 128 *:22 *:* owners']
        output = io.StringIO()
        with patch.object(m.guest, 'command', side_effect=values), \
                patch.object(m.guest.Path, 'read_text', side_effect=['1', 'finite']), \
                contextlib.redirect_stdout(output):
            status = m.guest.main()
        result = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(result['schema'], 1)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['details']['row'], '? 23 worker')
        self.assertFalse(result['physicalHardwareAssessed'])
        self.assertNotIn('accepted', result)

    def test_diagnostic_error_cannot_become_qualification(self):
        path = self.root / 'vm-fresh/first-boot-desktop.json'
        path.write_text(json.dumps({'schema': 1, 'status': 'error',
            'error': 'Malformed or unlabelled candidate process observation',
            'details': {'stage': 'processes', 'rowNumber': 2, 'row': '? 23 worker',
                        'rowLength': 11, 'truncated': False}, 'physicalHardwareAssessed': False}))
        with self.assertRaises((ValueError, KeyError)):
            m.assemble(self.root, self.acceptance)
        forged = {**self.observation, 'status': 'error', 'details': {'row': '? 23 worker'}}
        path.write_text(json.dumps(forged))
        with self.assertRaises(ValueError):
            m.assemble(self.root, self.acceptance)

    def state_observation(self, extra='', init='S', ssh='S'):
        processes = (f'system_u:system_r:init_t:s0 1 {init} 6 systemd\n'
                     f'system_u:system_r:sshd_t:s0 22 {ssh} 1 sshd')
        return m.guest.observations('Enforcing', '1', '', processes + ('\n' + extra if extra else ''),
            'tcp LISTEN 0 128 *:22 *:* owners', 'finite', process_format='state-threads')

    def test_explicit_single_thread_zombie_is_retained_without_name_exception(self):
        for label in ('-', '?'):
            for name in ('setroubleshootd <defunct>', 'other-worker', 'sshd'):
                observed = self.state_observation(f'{label} 2482 Z 1 {name}')
                self.assertEqual(observed['schema'], 2)
                self.assertEqual(observed['processes'][-1],
                    {'context': label, 'pid': 2482, 'state': 'Z', 'nlwp': 1, 'command': name})
                m.validate_observations(observed, 'finite')

    def test_zombie_group_leader_with_live_threads_is_not_exempt(self):
        for count in (2, 4, 1024):
            with self.subTest(nlwp=count), self.assertRaises(m.guest.ProcessObservationError):
                self.state_observation(f'- 2482 Z {count} setroubleshootd <defunct>')

    def test_live_or_other_dead_unlabelled_processes_are_not_exempt(self):
        for state in m.guest.PROCESS_STATES - {'Z'}:
            with self.subTest(state=state), self.assertRaises(m.guest.ProcessObservationError):
                self.state_observation(f'- 2482 {state} 1 setroubleshootd <defunct>')
        with self.assertRaises(m.guest.ProcessObservationError):
            self.state_observation('unconfined 2482 Z 1 worker')

    def test_state_pid_and_thread_fields_fail_closed(self):
        for row in ('- 2482 Z+ 1 worker', '- 2482 Q 1 worker', '- 2482 Z 0 worker',
                    '- 2482 Z -1 worker', '- 2482 Z 1.0 worker', '- 2482 Z ٢ worker',
                    '- 2482 Z True worker', '- 2482 Z 2147483648 worker', '- 0 Z 1 worker',
                    '- -1 Z 1 worker', '- ٢ Z 1 worker', '- 2147483648 Z 1 worker',
                    '- 2482 Z worker', 'system_u:system_r:worker_t:s0 22 S 1 duplicate'):
            with self.subTest(row=row), self.assertRaises(m.guest.ProcessObservationError):
                self.state_observation(row)

    def test_dead_rows_cannot_witness_init_or_confined_ssh(self):
        for state in ('Z', 'X', 'x'):
            for witness in ('init', 'ssh'):
                with self.subTest(state=state, witness=witness), self.assertRaises(ValueError):
                    self.state_observation(**{witness: state})
        with self.assertRaises(ValueError):
            m.guest.observations('Enforcing', '1', '',
                '- 1 Z 1 systemd\nsystem_u:system_r:sshd_t:s0 22 S 1 sshd',
                'tcp LISTEN 0 128 *:22 *:* owners', 'finite', process_format='state-threads')

    def test_new_schema_retains_enforcement_and_permissive_ssh_rejections(self):
        observed = self.state_observation('- 2482 Z 1 worker')
        for mutate in (lambda r: r['selinux'].update(mode='Permissive'),
                       lambda r: r['selinux'].update(kernelEnforce=0),
                       lambda r: r['selinux'].update(permissiveDomains=['sshd_t']),
                       lambda r: r['checks'].update(sshConfined=False)):
            bad = copy.deepcopy(observed); mutate(bad)
            with self.assertRaises(ValueError): m.validate_observations(bad, 'finite')

    def test_receipt_revalidates_state_threads_and_schema_even_with_new_hash(self):
        self.observation = self.state_observation('- 2482 Z 1 worker')
        (self.root/'vm-fresh/first-boot-desktop.json').write_text(json.dumps(self.observation))
        m.assemble(self.root, self.acceptance)
        path = m.verify(self.root, self.acceptance)
        original = path.read_bytes()
        for mutate in (lambda r: r.update(schema=1), lambda r: r.update(schema=3),
                       lambda r: r.update(schema=True), lambda r: r['processes'][-1].update(state='S'),
                       lambda r: r['processes'][-1].update(nlwp=2),
                       lambda r: r['processes'][-1].update(nlwp=True),
                       lambda r: r['processes'][-1].update(nlwp='1'),
                       lambda r: r['processes'][-1].update(nlwp=1.0),
                       lambda r: r['processes'][-1].pop('nlwp')):
            receipt = json.loads(original); mutate(receipt['phases']['fresh']['observations'])
            raw = json.dumps(receipt).encode(); path.write_bytes(raw)
            self.acceptance['vmSecurityEvidence']['sha256'] = hashlib.sha256(raw).hexdigest()
            with self.assertRaises(ValueError): m.verify(self.root, self.acceptance)

    def test_mixed_legacy_fresh_and_new_upgrade_receipts_validate(self):
        self.acceptance['previousDigest'] = 'sha256:'+'e'*64
        self.observation = self.state_observation('- 2482 Z 1 worker')
        self.write_phase('upgrade', 'updated', 'target')
        m.assemble(self.root, self.acceptance)
        receipt = json.loads(m.verify(self.root, self.acceptance).read_text())
        self.assertEqual(receipt['phases']['fresh']['observations']['schema'], 1)
        self.assertEqual(receipt['phases']['upgrade']['observations']['schema'], 2)
        # A legacy '-' row still has no state/nlwp proof and remains rejected.
        legacy = copy.deepcopy(self.observation); legacy['schema'] = 1
        for row in legacy['processes']:
            row.pop('state'); row.pop('nlwp')
        with self.assertRaises(ValueError): m.validate_observations(legacy, 'finite')

    def test_main_collects_explicit_state_threads_and_never_command_arguments(self):
        values = ['Enforcing', '', 'system_u:system_r:init_t:s0 1 S 6 systemd\n'
                  'system_u:system_r:sshd_t:s0 22 S 1 sshd\n- 2482 Z 1 worker',
                  'tcp LISTEN 0 128 *:22 *:* owners']
        output = io.StringIO()
        with patch.object(m.guest, 'command', side_effect=values) as command, \
                patch.object(m.guest.Path, 'read_text', side_effect=['1', 'finite']), \
                contextlib.redirect_stdout(output):
            self.assertEqual(m.guest.main(), 0)
        self.assertIn(unittest.mock.call(['ps', '-e', '-o', 'label=,pid=,state=,nlwp=,comm=']), command.call_args_list)
        observed = json.loads(output.getvalue())
        self.assertEqual(observed['schema'], 2)
        m.validate_observations(observed, 'finite')

    def test_new_format_keeps_all_rows_and_inventory_bounds(self):
        labelled = self.state_observation('system_u:system_r:worker_t:s0 2482 Z 8 worker')
        self.assertEqual(labelled['processes'][-1]['nlwp'], 8)
        with self.assertRaises(ValueError):
            self.state_observation('\n'.join(f'- {pid} Z 1 worker' for pid in range(100, 8300)))


if __name__ == '__main__': unittest.main()
