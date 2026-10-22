#!/usr/bin/env python3
"""CI cost controls retain full checks and publication authority boundaries."""
import importlib.util
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which('bash')


def workflow(name):
    return yaml.safe_load((ROOT / '.github/workflows' / (name + '.yml')).read_text())


class Savings(unittest.TestCase):
    def test_documentation_install_only_requests_missing_tools(self):
        command = next(step['run'] for step in workflow('build')['jobs']['docs']['steps']
                       if step.get('name') == 'Install documentation check tools')
        for present in ((), ('rg',), ('file',), ('rg', 'file')):
            with self.subTest(present=present), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name in (*present, 'sudo'):
                    path = root / name
                    path.write_text('#!' + BASH + '\nprintf "%s\\n" "$*" >> "$INSTALL_LOG"\n' if name == 'sudo' else '#!' + BASH + '\nexit 0\n')
                    path.chmod(0o755)
                log = root / 'commands'
                subprocess.run([BASH, '-e', '-c', command], check=True,
                               env={**os.environ, 'PATH': directory, 'INSTALL_LOG': str(log)})
                missing = [package for executable, package in (('rg', 'ripgrep'), ('file', 'file')) if executable not in present]
                self.assertEqual(log.read_text().splitlines() if log.exists() else [],
                                 ['apt-get update', 'apt-get install --no-install-recommends -y ' + ' '.join(missing)] if missing else [])

    def test_observers_ignore_validation_completions_but_keep_failed_main_and_hourly_health(self):
        data = workflow('delivery-health')
        triggers = data.get('on', data.get(True))
        self.assertEqual(triggers['workflow_run']['branches'], ['main'])
        self.assertEqual(triggers['workflow_run']['types'], ['completed'])
        self.assertIn('schedule', triggers)
        for name in ('health', 'reconcile'):
            guard = data['jobs'][name]['if']
            self.assertIn("github.event_name != 'workflow_run'", guard)
            self.assertIn("head_repository.full_name == 'closure-labs/finite'", guard)
            self.assertIn("head_branch == 'main'", guard)
            for event in ('push', 'schedule', 'workflow_dispatch'):
                self.assertIn("event == '" + event + "'", guard)
            self.assertNotIn('conclusion', guard, 'Failed main delivery must still be monitored')
        token = next(s for s in data['jobs']['health']['steps'] if s.get('id') == 'review-token')['with']
        self.assertTrue(all(v == 'read' for k, v in token.items() if k.startswith('permission-')))

    def test_signer_never_receives_full_products_and_keeps_environment_gate(self):
        data = workflow('publish-release-set')['jobs']
        self.assertEqual(data['sign']['environment'], 'release')
        request = [s for s in data['prepare']['steps'] if s.get('uses', '').startswith('actions/upload-artifact@')]
        self.assertEqual(len(request), 3, 'Preparation retains identity, signing evidence and failure diagnostics')
        self.assertEqual(request[1]['with']['path'], '.bluebuild/release-signing-request/')
        self.assertEqual(request[2]['if'], 'failure()')
        self.assertNotIn('/signed/', request[2]['with']['path'])
        self.assertNotIn('/transport/', request[2]['with']['path'])
        for phase in ('sign', 'publish'):
            download = next(s for s in data[phase]['steps'] if ' download ' in s.get('run', ''))
            self.assertIn('--metadata-only', download['run'])
            self.assertEqual(download['env']['ARTIFACT_READ_TOKEN'], '${{ github.token }}')
        signing = next(s for s in data['sign']['steps'] if 'release-signing --' in s.get('run', ''))
        self.assertIn('--metadata-only', signing['run'])
        self.assertTrue(any(' check --metadata-only ' in s.get('run', '') for s in data['sign']['steps']))

    def test_bounded_cache_does_not_repack_per_source_revision_or_allow_pr_writes(self):
        action = yaml.safe_load((ROOT / '.github/actions/setup-nix/action.yml').read_text())
        cache = next(s for s in action['runs']['steps'] if s.get('id') == 'store-cache')['with']
        self.assertIn('nix-checks-v3-', cache['primary-key'])
        self.assertIn("inputs.cache-mode == 'baseline'", cache['primary-key'])
        self.assertNotIn('github.sha', cache['primary-key'].split("|| format('nix-checks-v3-")[1])
        self.assertEqual(cache['gc-max-store-size-linux'], "${{ inputs.cache-mode != 'baseline' && '1G' || '' }}")
        self.assertIn("github.ref == 'refs/heads/main'", cache['save'])
        self.assertNotIn("github.event_name == 'pull_request'", cache['save'])
        self.assertIn('nix-store-v2-', cache['restore-prefixes-first-match'])

    def test_v2_fallback_is_retired_only_after_two_bounded_dependency_generations(self):
        spec = importlib.util.spec_from_file_location('cache_retention_fixture', ROOT / 'tests/ci/prune-ci-caches.py')
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        old = [fixture.cache(i) for i in (1, 2)]
        def bounded(i, ref='refs/heads/main'):
            return dict(fixture.cache(i, ref=ref), key='nix-checks-v3-Linux-X64-' + f'{i:064x}')
        self.assertEqual(fixture.prune.deletions(old + [bounded(3)]), [])
        self.assertEqual(fixture.prune.deletions(old + [bounded(3), bounded(4, 'refs/pull/1/merge')]), [])
        self.assertEqual([x['id'] for x in fixture.prune.deletions(old + [bounded(3), bounded(4), bounded(5)])], [1, 2, 3])


if __name__ == '__main__':
    unittest.main()
