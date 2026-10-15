#!/usr/bin/env python3
"""Exercise manual channel selection through payload selection and the CI gate."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import gate
import impact
import payloads

spec = importlib.util.spec_from_file_location('release_selection', ROOT / 'scripts/ci/release-selection.py')
selection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selection)


class ReleaseSelection(unittest.TestCase):
    def test_diagnostic_is_explicit_single_channel_and_cannot_publish_or_resume(self):
        arguments = [True, 'workflow_dispatch', 'finite', False, '', '',
                     'closure-labs/finite', 'refs/heads/security/release-eligibility']
        selection.validate_diagnostic(*arguments)
        for index, value in ((0, 'true'), (1, 'pull_request'), (2, 'automatic'),
                             (2, 'finite-next'), (2, 'finite-dev-next'), (3, True),
                             (4, '123'), (5, 'sha256:' + 'a' * 64), (6, 'fork/finite'),
                             (7, 'refs/heads/main'), (7, 'refs/tags/v1')):
            changed = arguments.copy()
            changed[index] = value
            with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                selection.validate_diagnostic(*changed)
        selection.validate_diagnostic(False, 'push', 'automatic', False, '', '', '', '')

    def test_resume_requires_explicit_main_channel_and_both_origin_identifiers(self):
        arguments = ['workflow_dispatch', 'finite', False, '123', 'sha256:' + 'a' * 64,
                     'closure-labs/finite', 'refs/heads/main']
        selection.validate_resume(*arguments)
        for index, value in ((0, 'push'), (1, 'automatic'), (1, 'finite-next'), (1, 'finite-dev-next'),
                             (2, True), (3, ''), (3, '../123'),
                             (4, ''), (4, 'latest'), (5, 'other/repo'), (6, 'refs/heads/feature')):
            changed = arguments.copy()
            changed[index] = value
            with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                selection.validate_resume(*changed)
        selection.validate_resume('push', 'automatic', False, '', '', '', '')

    def test_each_channel_selects_only_its_profile_and_requires_checks(self):
        expected = {'finite': 'finite', 'finite-dev': 'finite-dev'}
        for channel, profile in expected.items():
            with self.subTest(channel=channel):
                plan = selection.select('workflow_dispatch', channel, False)
                self.assertEqual(plan, {'checks': True, 'nix': False, 'profiles': [profile]})
                def unexpected_evaluation(_revision):
                    self.fail('Explicit manual scope must not require a nonexistent base revision')
                selected, evidence = payloads.refine(plan, 'workflow_dispatch', {}, 'a' * 40,
                                                     evaluator=unexpected_evaluation)
                self.assertEqual(selected, [profile])
                self.assertIsNone(evidence)

    def test_automatic_never_overrides_existing_event_selection(self):
        for event in ('push', 'pull_request', 'merge_group', 'schedule', 'workflow_dispatch'):
            for reconcile in (False, True):
                with self.subTest(event=event, reconcile=reconcile):
                    self.assertIsNone(selection.select(event, 'automatic', reconcile))
        for paths in (['README.md'], ['files/scripts/upstream-kernel.py'], ['flake.lock'], []):
            automatic = impact.classify(paths)
            self.assertEqual(selection.select('push', 'automatic', False) or automatic,
                             impact.classify(paths))

    def test_nonmanual_events_cannot_narrow_required_checks(self):
        for event in ('push', 'pull_request', 'merge_group', 'schedule', 'unknown'):
            for channel in selection.CHANNELS:
                with self.subTest(event=event, channel=channel), self.assertRaises(ValueError):
                    selection.select(event, channel, False)

    def test_invalid_scope_and_conflicting_reconciliation_fail_closed(self):
        for target in ('finite-next', 'finite-dev-next', '', 'all', 'latest', 'bluefin-generic', '../finite', 'finite\nchecks=false', None, []):
            with self.subTest(target=target), self.assertRaises(ValueError):
                selection.select('workflow_dispatch', target, False)
        for channel in selection.CHANNELS:
            with self.subTest(channel=channel), self.assertRaises(ValueError):
                selection.select('workflow_dispatch', channel, True)
        for value in ('false', 0, None):
            with self.subTest(reconcile=value), self.assertRaises(ValueError):
                selection.select('workflow_dispatch', 'finite', value)

    def needs(self, channel, publish):
        plan = selection.select('workflow_dispatch', channel, False)
        profile = plan['profiles'][0]
        return {
            'impact': {'result': 'success', 'outputs': {key: json.dumps(value) for key, value in plan.items()}},
            'docs': {'result': 'success'},
            'checks': {'result': 'success', 'outputs': {'images': 'true',
                       'matrix': json.dumps({'include': [{'profile': profile, 'channel': channel}]})}},
            'images': {'result': 'skipped' if publish else 'success'},
            'publish': {'result': 'success' if publish else 'skipped'},
        }

    def test_target_cannot_skip_checks_or_failed_publication(self):
        for channel in selection.CHANNELS:
            for publish in (False, True):
                needs = self.needs(channel, publish)
                self.assertEqual(gate.failures(needs, publish), [])
                for job in ('docs', 'checks', 'publish' if publish else 'images'):
                    for status in ('failure', 'cancelled', 'skipped'):
                        bad = copy.deepcopy(needs)
                        bad[job]['result'] = status
                        with self.subTest(channel=channel, publish=publish, job=job, status=status):
                            self.assertTrue(gate.failures(bad, publish))
                missing = copy.deepcopy(needs)
                missing['checks']['outputs'] = {'images': 'false', 'matrix': '{"include":[]}'}
                self.assertTrue(gate.failures(missing, publish))

    def invoke(self, **environment):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            summary = Path(directory) / 'summary'
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/ci/release-selection.py')],
                                    env={**os.environ, 'GITHUB_EVENT_NAME': 'workflow_dispatch',
                                         'RELEASE_TARGET': 'automatic', 'RECONCILE': 'false',
                                         'GITHUB_OUTPUT': str(output), 'GITHUB_STEP_SUMMARY': str(summary),
                                         **environment}, capture_output=True, text=True)
            return result, output.read_text() if output.exists() else '', summary.read_text() if summary.exists() else ''

    def test_command_outputs_are_compatible_with_github_and_payload_selection(self):
        for channel, profile in selection.CHANNELS.items():
            result, output, summary = self.invoke(RELEASE_TARGET=channel)
            self.assertEqual(result.returncode, 0, result.stderr)
            values = dict(line.split('=', 1) for line in output.splitlines())
            self.assertEqual(values.pop('selected'), 'true')
            plan = {key: json.loads(value) for key, value in values.items()}
            self.assertEqual(payloads.refine(plan, 'workflow_dispatch', {}, 'a' * 40)[0], [profile])
            self.assertIn(channel, summary)
        result, output, summary = self.invoke(GITHUB_EVENT_NAME='push')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, 'selected=false\n')
        self.assertEqual(summary, '')

    def test_command_rejection_emits_no_partial_selection(self):
        for environment in ({'RELEASE_TARGET': 'latest'}, {'RECONCILE': 'yes'},
                            {'RELEASE_TARGET': 'finite', 'RECONCILE': 'true'},
                            {'RELEASE_TARGET': 'finite', 'RESUME_RUN': '123'},
                            {'RELEASE_TARGET': 'finite', 'GITHUB_EVENT_NAME': 'merge_group'}):
            result, output, summary = self.invoke(**environment)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Release selection failed:', result.stderr)
            self.assertEqual((output, summary), ('', ''))


if __name__ == '__main__':
    unittest.main()
