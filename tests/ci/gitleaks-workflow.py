"""Small Git-graph, native job wiring and optional cached-engine fixtures."""
import json
import hashlib
import copy
import importlib.util
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import io
import zipfile
from datetime import datetime, timezone
from contextlib import ExitStack
from unittest.mock import patch
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/build.yml'

import yaml
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import gate
import finding_id_packets as packets


def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def scan_script():
    return next(step['run'] for step in workflow()['jobs']['repository-secrets']['steps']
                if step.get('name') == 'Scan complete introduced commit range')


class RangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'candidate'
        self.repo.mkdir()
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1')
        self.git('init', '-q', '-b', 'main')
        self.commit('base.txt', 'pre-existing-marker\n')
        self.base = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-q', '-b', 'side')
        self.commit('side.txt', 'side-introduced-then-deleted-marker\n')
        self.side = self.git('rev-parse', 'HEAD')
        self.git('rm', '-q', 'side.txt')
        self.git('commit', '-qm', 'remove side fixture')
        self.git('checkout', '-q', 'main')
        self.commit('main.txt', 'main-introduced-marker\n')
        self.git('merge', '--no-ff', '--no-commit', 'side')
        self.commit('merge-only.txt', 'merge-only-resolution-marker\n')
        self.head = self.git('rev-parse', 'HEAD')
        self.runtime = self.root / 'runtime'
        (self.runtime / 'gitleaks').mkdir(parents=True)
        binary = self.runtime / 'gitleaks/gitleaks'
        binary.write_text('#!' + sys.executable + '\nimport json,os,sys\nfrom pathlib import Path\nPath(os.environ["ARG_LOG"]).write_text(json.dumps(sys.argv[1:]))\nprint("DO-NOT-EXPOSE-FIXTURE-PAYLOAD")\nsys.exit(int(os.environ.get("SCANNER_EXIT","0")))\n')
        binary.chmod(0o755)

    def git(self, *args):
        return subprocess.check_output(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null', *args], cwd=self.repo, env=self.env, stderr=subprocess.DEVNULL, text=True).strip()

    def commit(self, name, text):
        (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / name).write_text(text)
        self.git('add', name)
        self.git('commit', '-qm', 'synthetic fixture')

    def run_scan(self, **values):
        env = dict(self.env, EVENT_NAME='pull_request', BASE_SHA=self.base, HEAD_SHA=self.head,
                   RUNNER_TEMP=str(self.runtime), GITHUB_WORKSPACE=str(self.root), ARG_LOG=str(self.root / 'args.json'),
                   GITHUB_REPOSITORY='closure-labs/finite', BASE_REPOSITORY='closure-labs/finite', BASE_REF='main')
        env.update(values)
        return subprocess.run(['bash', '-c', scan_script()], cwd=self.repo, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def test_complete_graph_and_merge_only_content(self):
        result = self.run_scan()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads((self.root / 'args.json').read_text())
        opts = next(a.split('=', 1)[1] for a in args if a.startswith('--log-opts='))
        self.assertNotIn('--first-parent ', opts)
        self.assertNotIn('--no-merges', opts)
        patch = self.git('log', '-p', '-U0', *opts.split())
        for marker in ['side-introduced-then-deleted-marker', 'merge-only-resolution-marker', 'main-introduced-marker']:
            self.assertIn('+' + marker, patch)
        self.assertNotIn('+pre-existing-marker', patch)
        self.assertIn(self.side, patch)
        self.assertNotIn('DO-NOT-EXPOSE', result.stdout + result.stderr)
        self.assertIn('--redact=100', args)
        self.assertFalse(any(a.startswith('--report') or a.startswith('--baseline') for a in args))
        self.assertEqual(self.run_scan(EVENT_NAME='merge_group').returncode, 0)
        for author in ('dependabot[bot]', 'ordinary-contributor'):
            self.assertEqual(self.run_scan(GITHUB_ACTOR=author).returncode, 0)

    def test_missing_bad_equal_and_wrong_checkout_fail_before_scanner(self):
        for values in [{'BASE_SHA': ''}, {'BASE_SHA': '1' * 40}, {'HEAD_SHA': 'not-a-sha'},
                       {'BASE_SHA': self.head}, {'HEAD_SHA': self.base}, {'HEAD_SHA': ''},
                       *({'EVENT_NAME': event} for event in ('workflow_run', 'pull_request_target', 'push', 'schedule', 'workflow_dispatch'))]:
            with self.subTest(values=values):
                result = self.run_scan(**values)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / 'args.json').exists())

    def test_diverged_pr_base_is_valid_but_queue_base_must_be_ancestor(self):
        self.git('checkout', '-q', '-b', 'new-base', self.base)
        self.commit('new-base.txt', 'new base data\n')
        diverged = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-q', 'main')
        self.assertEqual(self.run_scan(BASE_SHA=diverged).returncode, 0)
        self.assertNotEqual(self.run_scan(BASE_SHA=diverged, EVENT_NAME='merge_group').returncode, 0)

    def test_shallow_checkout_fails(self):
        (self.repo / '.git/shallow').write_text(self.base + '\n')
        self.assertNotEqual(self.run_scan().returncode, 0)
        self.assertFalse((self.root / 'args.json').exists())

    def test_actual_shallow_clone_fails_before_scanner(self):
        clone = self.root / 'shallow'
        subprocess.run(['git', 'clone', '-q', '--depth=1', self.repo.as_uri(), str(clone)],
                       env=self.env, check=True, capture_output=True)
        self.repo = clone
        self.assertEqual(self.git('rev-parse', '--is-shallow-repository'), 'true')
        self.assertNotEqual(self.run_scan().returncode, 0)
        self.assertFalse((self.root / 'args.json').exists())

    def test_existing_but_unrelated_base_fails_before_scanner(self):
        self.git('checkout', '-q', '--orphan', 'unrelated')
        self.commit('unrelated.txt', 'unrelated root\n')
        unrelated = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-q', 'main')
        for event in ('pull_request', 'merge_group'):
            self.assertNotEqual(self.run_scan(BASE_SHA=unrelated, EVENT_NAME=event).returncode, 0)
            self.assertFalse((self.root / 'args.json').exists())

    def test_findings_errors_and_timeouts_never_pass_or_leak(self):
        for status in [1, 2, 124, 137]:
            result = self.run_scan(SCANNER_EXIT=str(status))
            self.assertEqual(result.returncode, status)
            self.assertNotIn('DO-NOT-EXPOSE', result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('gitleaks'), 'Optional cached Gitleaks binary unavailable')
    def test_real_default_engine_blocks_new_findings_but_not_old_history(self):
        binary = self.runtime / 'gitleaks/gitleaks'
        binary.unlink()
        binary.symlink_to(shutil.which('gitleaks'))
        self.assertEqual(subprocess.check_output([str(binary), 'version'], text=True).strip(), '8.30.1')
        # Synthetic recognizable token, assembled only within this temporary Git graph.
        token = 'ghp_' + '9F0r2JtQ6Lw8aD3sG7hK1mN5pR4vXyZcBeTu'
        self.commit('old-token.txt', 'token = "' + token + '"\n')
        historical = self.git('rev-parse', 'HEAD')
        self.commit('clean.txt', 'new harmless content\n')
        clean = self.git('rev-parse', 'HEAD')
        self.assertEqual(self.run_scan(BASE_SHA=historical, HEAD_SHA=clean).returncode, 0)
        self.commit('.gitleaks.toml', '[extend]\nuseDefault = true\n[allowlist]\nregexes = [".+"]\n')
        self.commit('.gitleaksignore', '*\n')
        self.commit('new-token.txt', 'token = "' + token + '" # gitleaks:allow\n')
        introduced = self.git('rev-parse', 'HEAD')
        self.assertEqual(self.run_scan(BASE_SHA=historical, HEAD_SHA=introduced).returncode, 2)
        self.git('rm', '-q', 'new-token.txt')
        self.git('commit', '-qm', 'remove synthetic token')
        deleted = self.git('rev-parse', 'HEAD')
        self.assertEqual(self.run_scan(BASE_SHA=historical, HEAD_SHA=deleted).returncode, 2)
        self.git('remote', 'add', 'origin', str(self.repo))
        history = yaml.safe_load((ROOT / '.github/workflows/repository-secret-history.yml').read_text())
        script = next(s['run'] for s in history['jobs']['history']['steps']
                      if s.get('name') == 'Audit all fetched branch tag and pull-request history')
        shutil.copytree(ROOT / 'scripts/ci', self.repo / 'scripts/ci')
        shutil.copytree(ROOT / '.github/security', self.repo / '.github/security')
        result = subprocess.run(['bash', '-c', script], cwd=self.repo,
                                env=dict(self.env, RUNNER_TEMP=str(self.runtime), GITHUB_SHA=deleted, GITHUB_RUN_ID='7', GITHUB_RUN_ATTEMPT='1'), capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(token, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['verdict'], 'findings')

    def real_engine(self):
        binary = self.runtime / 'gitleaks/gitleaks'
        binary.unlink()
        binary.symlink_to(shutil.which('gitleaks'))
        self.assertEqual(subprocess.check_output([str(binary), 'version'], text=True).strip(), '8.30.1')

    @staticmethod
    def finding_packet():
        finding = {'profile': 'finite', 'component': 'pkg:rpm/fedora/example',
                   'advisory': 'CVE-2026-12345', 'exposure': ['/usr/bin/example'],
                   'severity': 'High', 'cvss': 8.0, 'knownExploited': False,
                   'versions': ['1'], 'aliases': ['CVE-2026-12345'], 'fixVersions': []}
        finding['key'] = RangeTests.packet_hash({k: finding[k] for k in
                                               ('profile', 'component', 'advisory', 'exposure')})
        return {'schema': 1, 'kind': 'security-findings', 'payload': {
            'profiles': ['finite'], 'findings': [finding], 'disposition': 'accept',
            'packet': {}, 'rationale': 'Synthetic finding identifier.', 'supersedes': []}}

    @staticmethod
    def packet_hash(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                         ensure_ascii=False, allow_nan=False).encode()).hexdigest()

    def inherit_packet(self, value, *, path=None, text=None):
        # The current protected base already contains the packet. A topic merge
        # reintroduces its bytes in a first-parent merge diff, just as in #321.
        self.git('branch', 'packet-topic')
        path = path or 'automation/decisions/security/' + self.packet_hash(value) + '.json'
        self.commit(path, text if text is not None else json.dumps(value, indent=2) + '\n')
        self.base = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-q', 'packet-topic')
        self.commit('topic.txt', 'topic change\n')
        self.git('merge', '-q', '--no-ff', '-m', 'inherit protected packet', 'main')
        self.head = self.git('rev-parse', 'HEAD')
        return path

    def ignored_fingerprints(self):
        return (self.runtime / 'verified-finding-ids.gitleaksignore').read_text().splitlines()

    @unittest.skipUnless(shutil.which('gitleaks'), 'Optional cached Gitleaks binary unavailable')
    def test_real_engine_exempts_only_recomputed_base_packet_id(self):
        self.real_engine()
        path = self.inherit_packet(self.finding_packet())
        # Prove that the unmodified default engine really detects this fixture.
        binary = self.runtime / 'gitleaks/gitleaks'
        (self.runtime / 'no-exceptions').write_text('')
        raw_args = [str(binary), 'git', '.', '--redact=100', '--no-banner',
            '--config', str(self.runtime / 'gitleaks-default.toml'),
            '--gitleaks-ignore-path', str(self.runtime / 'no-exceptions'), '--ignore-gitleaks-allow',
            '--exit-code=2', '--log-opts=--full-history --diff-merges=first-parent ' + self.base + '..' + self.head]
        # The config is written by the actual workflow, not candidate content.
        self.assertEqual(self.run_scan().returncode, 0)
        raw = subprocess.run(raw_args, cwd=self.repo, capture_output=True)
        self.assertEqual(raw.returncode, 2)
        ignored = self.ignored_fingerprints()
        self.assertEqual(len(ignored), 1)
        self.assertTrue(ignored[0].startswith(self.head + ':' + path + ':generic-api-key:'))
        for invalid in ({'BASE_REF': 'topic'}, {'BASE_REPOSITORY': 'other/finite'},
                        {'GITHUB_REPOSITORY': 'other/finite'}):
            self.assertEqual(self.run_scan(**invalid).returncode, 2)
            self.assertEqual(self.ignored_fingerprints(), [])
        self.assertEqual(self.run_scan(EVENT_NAME='merge_group', BASE_REF='refs/heads/main').returncode, 0)
        # Isolated Python must not import a candidate module while validating data.
        marker = self.root / 'candidate-executed'
        self.commit('json.py', 'from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n')
        self.head = self.git('rev-parse', 'HEAD')
        self.assertEqual(self.run_scan().returncode, 0)
        self.assertFalse(marker.exists())

    @unittest.skipUnless(shutil.which('gitleaks'), 'Optional cached Gitleaks binary unavailable')
    def test_real_engine_does_not_trust_key_labels_or_arbitrary_hex(self):
        self.real_engine()
        value = self.finding_packet()
        value['payload']['findings'][0]['key'] = hashlib.sha256(b'not-a-finding-identifier').hexdigest()
        self.inherit_packet(value)
        self.assertEqual(self.run_scan().returncode, 2)
        self.assertEqual(self.ignored_fingerprints(), [])

    @unittest.skipUnless(shutil.which('gitleaks'), 'Optional cached Gitleaks binary unavailable')
    def test_real_engine_does_not_exempt_modified_candidate_packets(self):
        self.real_engine()
        path = self.inherit_packet(self.finding_packet())
        value = self.finding_packet()
        finding = value['payload']['findings'][0]
        finding['component'] = 'pkg:rpm/fedora/changed-example'
        finding['key'] = self.packet_hash({k: finding[k] for k in
                                           ('profile', 'component', 'advisory', 'exposure')})
        self.commit(path, json.dumps(value, indent=2) + '\n')
        self.head = self.git('rev-parse', 'HEAD')
        self.assertEqual(self.run_scan().returncode, 2)
        self.assertTrue(all(not entry.startswith(self.head + ':') for entry in self.ignored_fingerprints()))

    @unittest.skipUnless(shutil.which('gitleaks'), 'Optional cached Gitleaks binary unavailable')
    def test_real_engine_does_not_exempt_new_candidate_packets(self):
        self.real_engine()
        self.inherit_packet(self.finding_packet())
        value = self.finding_packet()
        value['payload']['rationale'] = 'Candidate introduced a new packet.'
        new_path = 'automation/decisions/security/' + self.packet_hash(value) + '.json'
        self.commit(new_path, json.dumps(value, indent=2) + '\n')
        self.head = self.git('rev-parse', 'HEAD')
        self.assertEqual(self.run_scan().returncode, 2)
        self.assertTrue(all(not entry.startswith(self.head + ':') for entry in self.ignored_fingerprints()))

    @unittest.skipUnless(shutil.which('gitleaks'), 'Optional cached Gitleaks binary unavailable')
    def test_real_engine_still_detects_credentials_elsewhere_in_the_same_base_packet(self):
        self.real_engine()
        value = self.finding_packet()
        token = 'ghp_' + '9F0r2JtQ6Lw8aD3sG7hK1mN5pR4vXyZcBeTu'
        value['payload']['rationale'] = 'token = "' + token + '"'
        self.inherit_packet(value)
        result = self.run_scan()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(len(self.ignored_fingerprints()), 1)
        self.assertNotIn(token, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('gitleaks'), 'Optional cached Gitleaks binary unavailable')
    def test_real_engine_binds_ids_to_the_exact_json_path(self):
        self.real_engine()
        value = self.finding_packet()
        value['payload']['rationale'] = {'key': value['payload']['findings'][0]['key']}
        self.inherit_packet(value)
        self.assertEqual(self.run_scan().returncode, 2)
        self.assertEqual(len(self.ignored_fingerprints()), 1)

    @unittest.skipUnless(shutil.which('gitleaks'), 'Optional cached Gitleaks binary unavailable')
    def test_real_engine_rejects_minified_adjacent_secrets(self):
        self.real_engine()
        value = self.finding_packet()
        token = 'ghp_' + '9F0r2JtQ6Lw8aD3sG7hK1mN5pR4vXyZcBeTu'
        value['payload']['rationale'] = 'token = "' + token + '"'
        self.inherit_packet(value, text=json.dumps(value) + '\n')
        result = self.run_scan()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.ignored_fingerprints(), [])
        self.assertNotIn(token, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('gitleaks'), 'Optional cached Gitleaks binary unavailable')
    def test_real_engine_does_not_exempt_duplicate_json(self):
        self.real_engine()
        value = self.finding_packet()
        text = (json.dumps(value, indent=2) + '\n').replace(
            '    "rationale":', '    "rationale": "duplicate",\n    "rationale":', 1)
        self.inherit_packet(value, text=text)
        self.assertEqual(self.run_scan().returncode, 2)
        self.assertEqual(self.ignored_fingerprints(), [])

    @unittest.skipUnless(shutil.which('gitleaks'), 'Optional cached Gitleaks binary unavailable')
    def test_real_engine_does_not_exempt_other_packet_paths(self):
        self.real_engine()
        self.inherit_packet(self.finding_packet(), path='automation/decisions/security/not-content-addressed.json')
        self.assertEqual(self.run_scan().returncode, 2)
        self.assertEqual(self.ignored_fingerprints(), [])


class NativeGateTests(unittest.TestCase):
    def needs(self):
        return {'repository-secrets': {'result': 'success'},
                'impact': {'result': 'success', 'outputs': {'checks': 'false', 'nix': 'false', 'profiles': '[]'}},
                'docs': {'result': 'success'}, 'checks': {'result': 'skipped'},
                'images': {'result': 'skipped'}, 'publish': {'result': 'skipped'}}

    def test_scan_required_even_for_docs_and_no_images(self):
        for event in ('pull_request', 'merge_group'):
            self.assertEqual(gate.failures(self.needs(), False, event), [])
            for state in ('failure', 'cancelled', 'skipped', 'pending', None):
                needs = self.needs(); needs['repository-secrets']['result'] = state
                errors = gate.failures(needs, False, event)
                self.assertEqual(errors, ['Repository scan did not produce the required native job result'])
            needs = self.needs(); del needs['repository-secrets']
            needs['history'] = {'result': 'success'}
            needs['savedScan'] = {'result': 'success', 'head': 'old'}
            self.assertTrue(gate.failures(needs, False, event))

    def test_history_is_not_a_premerge_or_publication_scan_receipt(self):
        for event in ('push', 'schedule', 'workflow_dispatch'):
            needs = self.needs(); needs['repository-secrets']['result'] = 'skipped'
            self.assertEqual(gate.failures(needs, False, event), [])
            needs['repository-secrets']['result'] = 'success'
            self.assertTrue(gate.failures(needs, False, event))
        for event in ('workflow_run', 'pull_request_target', '', 'forged'):
            self.assertTrue(gate.failures(self.needs(), False, event))

    def test_native_same_run_dependency_and_real_job_name(self):
        jobs = workflow()['jobs']
        self.assertEqual(jobs['repository-secrets']['name'], 'Repository security audit')
        self.assertEqual(jobs['repository-secrets']['if'],
                         "github.event_name == 'pull_request' || github.event_name == 'merge_group'")
        self.assertEqual(jobs['repository-secrets']['permissions'], {'contents': 'read', 'actions': 'read'})
        self.assertIn('repository-secrets', jobs['gate']['needs'])
        self.assertEqual(jobs['gate']['name'], 'CI gate')
        self.assertEqual(jobs['gate']['if'], 'always()')
        self.assertEqual(jobs['gate']['env']['NEEDS'], '${{ toJSON(needs) }}')
        self.assertNotIn('uses', jobs['repository-secrets'])
        steps = jobs['repository-secrets']['steps']
        checkout = steps[0]['with']
        self.assertEqual(checkout['ref'], '${{ github.event.pull_request.head.sha || github.event.merge_group.head_sha }}')
        self.assertIs(checkout['persist-credentials'], False)
        self.assertEqual(checkout['fetch-depth'], 0)
        self.assertEqual(checkout['path'], 'candidate')
        env = next(s['env'] for s in steps if s.get('name') == 'Scan complete introduced commit range')
        self.assertEqual(env['BASE_SHA'], '${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha }}')
        self.assertEqual(env['HEAD_SHA'], checkout['ref'])
        self.assertEqual(env['BASE_REF'], '${{ github.event.pull_request.base.ref || github.event.merge_group.base_ref }}')
        self.assertEqual(env['BASE_REPOSITORY'], '${{ github.event.pull_request.base.repo.full_name || github.repository }}')

    def test_supported_triggers_and_history_main_guard(self):
        build = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(set(build['on']), {'pull_request', 'merge_group', 'push', 'schedule', 'workflow_dispatch'})
        self.assertEqual(build['on']['merge_group']['types'], ['checks_requested'])
        history = yaml.load((ROOT / '.github/workflows/repository-secret-history.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(set(history['on']), {'schedule', 'workflow_dispatch'})
        guard = history['jobs']['history']['steps'][0]['run']
        for ref, wanted in [('refs/heads/main', 0), ('refs/heads/topic', 1), ('refs/pull/7/merge', 1), ('', 1)]:
            result = subprocess.run(['bash', '-c', guard], env=dict(os.environ, GITHUB_REF=ref))
            self.assertEqual(result.returncode, wanted)

    def test_scanner_has_no_candidate_execution_credentials_or_exclusions(self):
        job = workflow()['jobs']['repository-secrets']
        history = yaml.safe_load((ROOT / '.github/workflows/repository-secret-history.yml').read_text())
        self.assertEqual(history['permissions'], {'contents': 'read'})
        self.assertEqual(history['jobs']['history']['name'], 'Repository historical audit (nonblocking debt)')
        self.assertEqual(history['jobs']['history']['steps'][0]['run'], 'test "$GITHUB_REF" = refs/heads/main')
        for jobs in (job, history['jobs']['history']):
            text = yaml.safe_dump(jobs)
            for forbidden in ('secrets.', 'token:', 'continue-on-error:', 'checks: write',
                              'id-token:', '--baseline', '--max-target-megabytes', 'uses: $/', 'uses: ./'):
                self.assertNotIn(forbidden, text)
            self.assertIn('551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb', text)
            run = next(s['run'] for s in jobs['steps'] if 'log_opts=' in s.get('run', ''))
            self.assertIn('useDefault = true', run)
            self.assertNotIn('allowlists', run)
            self.assertIn('--ignore-gitleaks-allow', run)
            expected = 'verified-finding-ids' if jobs is job else 'verified-history-ids'
            self.assertIn('--gitleaks-ignore-path "$RUNNER_TEMP/' + expected + '.gitleaksignore"', run)
            self.assertIn('>/dev/null 2>&1', run)
        self.assertNotIn('upload-artifact', yaml.safe_dump(job))
        uploads = [step for step in history['jobs']['history']['steps'] if 'upload-artifact@' in step.get('uses', '')]
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0]['with']['path'], '${{ runner.temp }}/finite-history-evidence/')
        self.assertNotIn('report', uploads[0]['with']['path'])
        incoming = scan_script()
        self.assertIn('python3 -I -', incoming)
        self.assertIn('blob(BASE, path)', incoming)
        self.assertIn('blob(commit, path) == oid', incoming)
        self.assertIn("canonical_hash({k: finding[k]", incoming)
        self.assertNotIn('import security_decisions', incoming)


class NewPacketTests(unittest.TestCase):
    git = RangeTests.git
    commit = RangeTests.commit
    run_scan = RangeTests.run_scan
    real_engine = RangeTests.real_engine

    def setUp(self):
        RangeTests.setUp(self)
        self.base = self.head
        self.controller = packets.decision_controller
        self.value = RangeTests.finding_packet()
        payload = self.value['payload']
        payload.update(profiles=['finite', 'finite-dev'], disposition='accepted')
        self.run = {'id': 7, 'path': '.github/workflows/build.yml', 'event': 'push', 'head_branch': 'main',
                    'status': 'completed', 'conclusion': 'failure', 'run_attempt': 2, 'head_sha': self.base,
                    'head_repository': {'full_name': 'closure-labs/finite'},
                    'created_at': '2026-01-01T00:00:00Z', 'updated_at': '2026-01-01T02:00:00Z'}
        reuse = self.controller.module('finding_fixture_reuse', ROOT / 'scripts/ci/reuse-candidate-security.py')
        self.files = {name: b'{}' for name in reuse.REQUIRED}
        self.zips, self.artifacts = {}, []
        for index, profile in enumerate(('finite', 'finite-dev'), 1):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as zipped:
                for name, raw in self.files.items():zipped.writestr(name, raw)
            raw = stream.getvalue();self.zips[index] = raw
            self.artifacts.append({'id': index, 'name': f'security-{profile}-7-2', 'expired': False,
                'workflow_run': {'id': 7, 'head_sha': self.base}, 'digest': 'sha256:' + hashlib.sha256(raw).hexdigest(),
                'size_in_bytes': len(raw), 'created_at': '2026-01-01T01:00:00Z'})
        origin = {'repository': 'closure-labs/finite', 'workflow': 'build.yml', 'runId': 7,
                  'runAttempt': 2, 'headSha': self.base,
                  'artifacts': [{k: a[k] for k in ('id', 'name', 'digest')} for a in self.artifacts]}
        data = {f'{profile}/{name}': raw for profile in ('finite', 'finite-dev') for name, raw in self.files.items()}
        inventory = {name: {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} for name, raw in data.items()}
        manifest = {'schema': 1, 'producer': origin, 'files': inventory}
        data['decision-packet.json'] = json.dumps(manifest).encode()
        self.blobs = {hashlib.sha256(raw).hexdigest(): raw for raw in data.values()}
        oci = {'schemaVersion': 2, 'artifactType': self.controller.decision_packets.TYPE,
               'layers': [{'annotations': {'org.opencontainers.image.title': name}, 'size': len(raw),
                           'digest': 'sha256:' + hashlib.sha256(raw).hexdigest()} for name, raw in data.items()]}
        self.oci = json.dumps(oci).encode()
        self.reference = self.controller.decision_packets.REGISTRY + '@sha256:' + hashlib.sha256(self.oci).hexdigest()
        payload['packet'] = {'reference': self.reference, 'sha256': packets.canonical_hash(manifest), 'producer': origin}
        self.stack = ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(self.controller, 'api', side_effect=self.api))
        self.stack.enter_context(patch.object(self.controller.decision_packets, 'command', side_effect=self.registry))
        self.original_run = subprocess.run
        self.stack.enter_context(patch.object(subprocess, 'run', side_effect=self.transport))
        self.stack.enter_context(patch.object(self.controller, 'native_result', side_effect=self.native))
        self.authenticated_calls = 0

    def api(self, endpoint, *args):
        if endpoint == 'repos/closure-labs/finite/actions/runs/7':return self.run
        if endpoint.startswith('repos/closure-labs/finite/actions/runs/7/artifacts?'):return {'artifacts': self.artifacts}
        raise AssertionError('Unexpected network endpoint')

    def registry(self, args, **kwargs):
        if args[1:3] == ['manifest', 'fetch']:
            if args[3] != self.reference:raise ValueError('Substituted OCI reference')
            return self.oci
        digest = args[3].split(':')[-1]
        Path(args[args.index('--output') + 1]).write_bytes(self.blobs[digest])
        return b''

    def transport(self, args, **kwargs):
        if args[:2] == ['gh', 'api']:
            artifact_id = int(args[2].split('/')[-2])
            kwargs['stdout'].write(self.zips[artifact_id])
            self.authenticated_calls += 1
            return subprocess.CompletedProcess(args, 0)
        return self.original_run(args, **kwargs)

    def native(self, directory, *args, profile=None, **kwargs):
        observation = {'component': 'pkg:rpm/fedora/example@1', 'advisory': 'CVE-2026-12345',
                       'locations': ['/usr/bin/example'], 'locationCoverage': 'complete',
                       'severity': 'High', 'cvss': 8.0, 'knownExploited': False,
                       'aliases': ['CVE-2026-12345'], 'fixVersions': []}
        return {'status': 'complete', 'scannerHealth': 'healthy',
                'observations': [observation] if profile == 'finite' else []}

    def add_packet(self, value=None, *, text=None, path=None):
        value = self.value if value is None else value
        path = path or 'automation/decisions/security/' + packets.canonical_hash(value) + '.json'
        self.commit(path, text if text is not None else json.dumps(value, indent=2) + '\n')
        self.head = self.git('rev-parse', 'HEAD')
        return path

    def receipt(self):
        values = packets.fingerprints(self.repo, self.base, self.head)
        (self.runtime / 'authenticated-finding-ids.gitleaksignore').write_text(''.join(v + '\n' for v in values))
        return values

    def test_full_byte_authentication_precedes_exact_exceptions(self):
        path = self.add_packet()
        values = self.receipt()
        self.assertEqual(self.authenticated_calls, 2)
        self.assertEqual(len(values), 1)
        self.assertTrue(values[0].startswith(self.head + ':' + path + ':generic-api-key:'))

    def test_substituted_provenance_request_and_archive_bytes_never_get_receipt(self):
        for kind in ('run', 'attempt', 'source', 'artifact', 'request', 'oci', 'zip', 'zip-digest', 'oci-bytes'):
            with self.subTest(kind=kind):
                value = copy.deepcopy(self.value)
                if kind == 'run':value['payload']['packet']['producer']['runId'] = 8
                if kind == 'attempt':value['payload']['packet']['producer']['runAttempt'] = 3
                if kind == 'source':value['payload']['packet']['producer']['headSha'] = 'f' * 40
                if kind == 'artifact':value['payload']['packet']['producer']['artifacts'][0]['digest'] = 'sha256:' + 'e' * 64
                if kind == 'request':value['payload']['packet']['sha256'] = 'e' * 64
                if kind == 'oci':value['payload']['packet']['reference'] = self.reference[:-1] + ('0' if self.reference[-1] != '0' else '1')
                path = 'automation/decisions/security/' + packets.canonical_hash(value) + '.json'
                raw = (json.dumps(value, indent=2) + '\n').encode()
                parsed, _ = packets.proposal_lines(raw, path)
                original_zip, original_blobs = self.zips.copy(), self.blobs.copy()
                try:
                    if kind == 'zip':self.zips[1] = b'wrong native archive bytes'
                    if kind == 'zip-digest':self.zips[1] = self.zips[1][:-1] + bytes([self.zips[1][-1] ^ 1])
                    if kind == 'oci-bytes':self.blobs = {key: bytes([raw[0] ^ 1]) + raw[1:] for key, raw in self.blobs.items()}
                    with self.assertRaises((ValueError, subprocess.CalledProcessError, AssertionError)):
                        packets.authenticate_packet(parsed, self.base, self.repo)
                finally:self.zips, self.blobs = original_zip, original_blobs

    def test_duplicate_minified_relocated_forged_and_spoofed_data_get_no_exception(self):
        valid = copy.deepcopy(self.value)
        raw = json.dumps(valid, indent=2) + '\n'
        cases = [(valid, raw.replace('"schema": 1,', '"schema": 1, "schema": 1,')),
                 (valid, json.dumps(valid))]
        forged = copy.deepcopy(valid);forged['payload']['findings'][0]['key'] = hashlib.sha256(b'not-the-finding').hexdigest()
        cases.append((forged, json.dumps(forged, indent=2) + '\n'))
        moved = copy.deepcopy(valid);moved['payload']['rationale'] = {'key': moved['payload']['findings'][0].pop('key')}
        cases.append((moved, json.dumps(moved, indent=2) + '\n'))
        for value, text in cases:
            path = 'automation/decisions/security/' + packets.canonical_hash(value) + '.json'
            with self.assertRaises(ValueError):packets.proposal_lines(text.encode(), path)
        with self.assertRaises(ValueError):packets.proposal_lines(raw.encode(), 'automation/decisions/security/not-content-addressed.json')

    @unittest.skipUnless(shutil.which('gitleaks'), 'Pinned Gitleaks supplied by dedicated hosted fixture job')
    def test_pinned_real_engine_accepts_only_authenticated_new_ids(self):
        self.real_engine();self.add_packet()
        self.assertEqual(self.run_scan().returncode, 2)
        self.receipt()
        self.assertEqual(self.run_scan().returncode, 0)

    @unittest.skipUnless(shutil.which('gitleaks'), 'Pinned Gitleaks supplied by dedicated hosted fixture job')
    def test_pinned_real_engine_still_blocks_credentials_elsewhere_in_authenticated_packet(self):
        self.real_engine()
        value = copy.deepcopy(self.value)
        token = 'ghp_' + '9F0r2JtQ6Lw8aD3sG7hK1mN5pR4vXyZcBeTu'
        value['payload']['rationale'] = 'Synthetic token=' + token
        self.add_packet(value);self.receipt()
        result = self.run_scan()
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(token, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('gitleaks'), 'Pinned Gitleaks supplied by dedicated hosted fixture job')
    def test_pinned_real_engine_blocks_unverified_new_ids(self):
        self.real_engine()
        value = copy.deepcopy(self.value);value['payload']['packet']['producer']['runAttempt'] = 3
        self.add_packet(value)
        with self.assertRaises(ValueError):self.receipt()
        self.assertEqual(self.run_scan().returncode, 2)

    @unittest.skipUnless(shutil.which('gitleaks'), 'Pinned Gitleaks supplied by dedicated hosted fixture job')
    def test_pinned_real_engine_rejects_all_ambiguous_or_unbound_new_packets(self):
        self.real_engine()
        original = copy.deepcopy(self.value)
        for kind in ('forged-id', 'duplicate-json', 'minified', 'relocated', 'path-spoof', 'same-line-secret'):
            with self.subTest(kind=kind):
                self.git('reset', '--hard', self.base)  # Owned synthetic temporary Git graph only.
                value = copy.deepcopy(original);path = None
                if kind == 'forged-id':value['payload']['findings'][0]['key'] = hashlib.sha256(b'forged-id').hexdigest()
                if kind == 'relocated':value['payload']['rationale'] = {'key': value['payload']['findings'][0].pop('key')}
                text = json.dumps(value, indent=2) + '\n'
                if kind == 'duplicate-json':text = text.replace('"schema": 1,', '"schema": 1, "schema": 1,')
                if kind == 'minified':text = json.dumps(value)
                if kind == 'path-spoof':path = 'automation/decisions/security/not-content-addressed.json'
                if kind == 'same-line-secret':
                    token = 'ghp_' + '9F0r2JtQ6Lw8aD3sG7hK1mN5pR4vXyZcBeTu'
                    key = value['payload']['findings'][0]['key']
                    text = text.replace('"key": "' + key + '"', '"key": "' + key + '", "token": "' + token + '"')
                self.add_packet(value, text=text, path=path)
                output = self.runtime / 'authenticated-finding-ids.gitleaksignore';output.write_text('')
                try:self.receipt()
                except ValueError:pass
                self.assertEqual(output.read_text(), '')
                self.assertEqual(self.run_scan().returncode, 2)

    def test_protected_base_absence_never_executes_candidate_helper(self):
        trusted = self.root / 'trusted-scanner'
        self.git('worktree', 'add', '--detach', str(trusted), self.base)
        marker = self.root / 'candidate-helper-executed'
        self.commit('scripts/ci/finding_id_packets.py', 'from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n')
        head = self.git('rev-parse', 'HEAD')
        step = next(s for s in workflow()['jobs']['repository-secrets']['steps'] if s.get('name') == 'Authenticate new packet finding IDs')
        result = subprocess.run(['bash', '-c', step['run']], cwd=self.repo,
            env={**self.env, 'RUNNER_TEMP': str(self.runtime), 'GITHUB_WORKSPACE': str(self.root),
                 'BASE_SHA': self.base, 'HEAD_SHA': head, 'BASE_REPOSITORY': 'closure-labs/finite',
                 'BASE_REF': 'main', 'EVENT_NAME': 'pull_request'}, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(marker.exists())
        self.assertEqual((self.runtime / 'authenticated-finding-ids.gitleaksignore').read_text(), '')

    def test_verifier_wrong_tool_source_clears_receipt_before_any_authentication(self):
        output = self.root / 'receipt';output.write_text('stale-ignore')
        env = {'BASE_SHA': self.base, 'HEAD_SHA': self.head, 'EVENT_NAME': 'pull_request',
               'BASE_REF': 'main', 'BASE_REPOSITORY': 'closure-labs/finite', 'GITHUB_REPOSITORY': 'closure-labs/finite'}
        with patch.dict(os.environ, env), patch.object(packets, 'git', return_value=b'wrong-source'), \
                patch.object(packets, 'fingerprints') as authenticate, \
                patch.object(sys, 'argv', ['helper', '--candidate', str(self.repo), '--output', str(output)]), self.assertRaises(ValueError):
            packets.main()
        authenticate.assert_not_called()
        self.assertEqual(output.read_text(), '')
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_existing_revocations_retain_full_scan_without_new_exceptions_or_auth_gate(self):
        value = copy.deepcopy(self.value)
        value['kind'] = 'security-revocation'
        value['payload']['disposition'] = 'revoked'
        value['payload']['supersedes'] = ['a' * 64]
        self.add_packet(value)
        value['payload']['rationale'] += ' second revocation'
        self.add_packet(value)
        self.assertEqual(self.receipt(), [])
        self.assertEqual(self.authenticated_calls, 0)

    def test_one_document_and_regular_blob_bounds(self):
        with self.assertRaises(ValueError):packets.proposal_lines(b' ' * (packets.MAX_DOCUMENT + 1), 'automation/decisions/security/' + 'a' * 64 + '.json')
        self.add_packet()
        value = copy.deepcopy(self.value);value['payload']['rationale'] += ' another request'
        self.add_packet(value)
        with self.assertRaisesRegex(ValueError, 'one immutable packet'):self.receipt()

    def test_workflow_credentials_belong_only_to_protected_base_verifier(self):
        job = workflow()['jobs']['repository-secrets']
        checkout = next(s for s in job['steps'] if s.get('name') == 'Checkout protected base scanner tools')
        self.assertEqual(checkout['with']['ref'], '${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha }}')
        self.assertIs(checkout['with']['persist-credentials'], False)
        auth = next(s for s in job['steps'] if s.get('name') == 'Authenticate new packet finding IDs')
        scan = next(s for s in job['steps'] if s.get('name') == 'Scan complete introduced commit range')
        self.assertEqual(auth['env']['GH_TOKEN'], '${{ github.token }}')
        self.assertNotIn('GH_TOKEN', scan['env'])
        self.assertIn('python3 -I "$helper"', auth['run'])
        self.assertIn('helper="$trusted/scripts/ci/finding_id_packets.py"', auth['run'])
        self.assertEqual(scan['if'], '${{ !cancelled() }}')
        self.assertNotIn('secrets.', yaml.safe_dump(job))


class NativeOriginTests(unittest.TestCase):
    def test_existing_build_origin_covers_dependabot_and_ordinary_prs(self):
        spec = importlib.util.spec_from_file_location('scanner_admission', ROOT / 'scripts/ci/ci-run-admission.py')
        admission = importlib.util.module_from_spec(spec); spec.loader.exec_module(admission)
        rules = json.loads((ROOT / 'automation/github/ci-execution.json').read_text())
        repo = {'id': rules['repositoryId'], 'full_name': rules['repository']}
        for author in ('dependabot[bot]', 'ordinary-contributor'):
            pr = {'user': {'login': author}, 'head': {'sha': 'a' * 40, 'ref': 'topic', 'repo': repo}}
            run = {'id': 10, 'run_attempt': 1, 'workflow_id': 50, 'repository': repo, 'head_repository': repo,
                   'head_branch': 'topic', 'head_sha': 'a' * 40, 'event': 'pull_request',
                   'path': '.github/workflows/build.yml'}
            self.assertTrue(admission.bound_run(run, pr, rules))
            for change in ({'head_sha': 'b' * 40}, {'head_branch': 'other'},
                           {'repository': {'id': 1}}, {'head_repository': {'id': 1}},
                           {'run_attempt': 0}, {'workflow_id': None}, {'event': 'workflow_run'}, {'event': 'workflow_dispatch'},
                           {'path': '.github/workflows/repository-secret-history.yml'},
                           {'path': '.github/workflows/forged.yml'}):
                with self.subTest(author=author, change=change):
                    self.assertFalse(admission.bound_run({**copy.deepcopy(run), **change}, pr, rules))
        # This is origin matching only; existing live author/reviewer eligibility still applies.
        self.assertNotIn('.github/workflows/repository-secret-history.yml', rules['workflows'])


if __name__ == '__main__': unittest.main()
