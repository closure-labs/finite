#!/usr/bin/env python3
"""Resume only immutable candidates from successful trusted original build jobs."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('resume_publication', ROOT / 'scripts/bluebuild/publication.py')
pub = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pub)


class Resume(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.profile = 'bluefin-generic'
        self.digest = 'sha256:' + 'd' * 64
        self.image = pub.upstream.REPOSITORY + '@' + self.digest
        self.identity = 'v1:' + 'e' * 64
        shutil.copytree(ROOT / 'recipes', self.root / 'recipes')
        self.git('init')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        self.git('add', '.')
        self.git('commit', '-m', 'Original runtime')
        self.source = self.git('rev-parse', 'HEAD')
        (self.root / 'policy-only.json').write_text('{"reviewedDigest": "' + self.digest + '"}\n')
        self.git('add', '.')
        self.git('commit', '-m', 'Review original digest')
        self.head = self.git('rev-parse', 'HEAD')
        self.recipe = pub.upstream.recipes(self.root)[self.profile]
        self.record = {**self.recipe, 'profile': self.profile, 'publish': True,
                       'revision': self.source, 'sourceRevision': self.source,
                       'buildIdentity': self.identity, 'qualificationMode': 'enforce'}
        self.info = {'Digest': self.digest, 'Os': 'linux', 'Architecture': 'amd64', 'Labels': {
            'io.finite.profile': self.profile, 'io.finite.build-inputs': self.identity,
            'org.opencontainers.image.revision': self.source,
            'org.opencontainers.image.base.digest': self.recipe['digest'],
            'org.opencontainers.image.source': 'https://github.com/closure-labs/finite'}}
        self.run = {'id': 123, 'run_attempt': 1, 'status': 'completed', 'conclusion': 'failure',
                    'event': 'push', 'head_branch': 'main', 'head_sha': self.source,
                    'path': '.github/workflows/build.yml',
                    'repository': {'full_name': 'closure-labs/finite'},
                    'head_repository': {'full_name': 'closure-labs/finite'}}
        self.jobs = [{'id': i + 10, 'name': name, 'head_sha': self.source,
                      'status': 'completed', 'conclusion': 'success', 'run_id': 123, 'run_attempt': 1,
                      'steps': [{'name': step, 'conclusion': 'success'} for step in (
                          'Prepare candidate publication', 'Build with BlueBuild', 'Verify assembled image', 'Save build evidence')]}
                     for i, name in enumerate(('Select checks', 'Documentation checks', 'Nix and runtime contracts',
                                               'Publish (bluefin-generic) / build / build'))]
        self.artifact = {'id': 456, 'name': 'image-bluefin-generic-123-1', 'expired': False,
                         'digest': 'sha256:' + 'f' * 64, 'size_in_bytes': 1234,
                         'workflow_run': {'id': 123, 'head_sha': self.source}}
        self.files = {self.profile + '-publication.json': json.dumps(self.record).encode(),
                      self.profile + '-image-ref.txt': (self.image + '\n').encode(),
                      self.profile + '.Containerfile': b'FROM reviewed-runtime\n'}
        env = patch.dict(os.environ, GITHUB_REPOSITORY='closure-labs/finite', GITHUB_REF='refs/heads/main',
                         GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_SHA=self.head, GITHUB_OUTPUT='',
                         FINITE_QUALIFICATION_MODE='enforce')
        env.start()
        self.addCleanup(env.stop)

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, stderr=subprocess.DEVNULL, text=True).strip()

    def metadata(self):
        return pub.origin_metadata(self.run, self.jobs, [self.artifact], self.profile, '123')

    def candidate(self):
        return pub.validate_candidate(self.profile, self.digest, self.source, self.record, self.image,
                                      self.info, self.recipe, self.identity)

    def test_failed_security_run_can_supply_successful_original_build(self):
        artifact, job = self.metadata()
        self.assertEqual(artifact, self.artifact)
        self.assertEqual(job, self.jobs[-1]['id'])
        for event in ('push', 'workflow_dispatch'):
            self.run['event'] = event
            self.metadata()

    def test_cancelled_parent_with_completed_trusted_build_can_resume_for_fresh_checks(self):
        self.run['conclusion'] = 'cancelled'
        self.invoke()
        evidence = self.root / '.bluebuild'
        record = json.loads((evidence / (self.profile + '-publication.json')).read_text())
        self.assertEqual(record['resumeOrigin']['runId'], self.run['id'])
        self.assertEqual(record['resumeOrigin']['runAttempt'], self.run['run_attempt'])
        self.assertEqual(record['resumeOrigin']['artifactDigest'], self.artifact['digest'])
        self.assertEqual(record['sourceRevision'], self.source)
        self.assertEqual(record['revision'], self.head)
        self.assertTrue(record['qualify'])
        self.assertEqual((evidence / (self.profile + '-image-ref.txt')).read_text().strip(), self.image)
        self.assertFalse((evidence / (self.profile + '-acceptance.json')).exists())
        self.assertFalse((evidence / (self.profile + '-promoted.json')).exists())

    def test_cancelled_parent_cannot_resume_cancelled_missing_or_partial_required_jobs(self):
        self.run['conclusion'] = 'cancelled'
        original = copy.deepcopy(self.jobs)
        for index in range(len(original)):
            for field, value in (('conclusion', 'cancelled'), ('conclusion', None),
                                 ('status', 'in_progress'), ('run_attempt', 2),
                                 ('head_sha', self.head), ('run_id', 124)):
                self.jobs = copy.deepcopy(original)
                self.jobs[index][field] = value
                with self.subTest(job=index, field=field, value=value), self.assertRaises(ValueError):
                    self.invoke()
            self.jobs = copy.deepcopy(original)
            del self.jobs[index]
            with self.subTest(missing=index), self.assertRaises(ValueError):
                self.invoke()
        self.assertFalse((self.root / '.bluebuild').exists())

    def test_cancelled_parent_cannot_resume_partial_steps_or_substituted_artifact(self):
        self.run['conclusion'] = 'cancelled'
        original = copy.deepcopy(self.jobs)
        for index in range(4):
            for conclusion in ('cancelled', 'skipped', None):
                self.jobs = copy.deepcopy(original)
                self.jobs[-1]['steps'][index]['conclusion'] = conclusion
                with self.subTest(step=index, conclusion=conclusion), self.assertRaises(ValueError):
                    self.invoke()
            self.jobs = copy.deepcopy(original)
            del self.jobs[-1]['steps'][index]
            with self.subTest(missing_step=index), self.assertRaises(ValueError):
                self.invoke()
        self.jobs = original
        original_artifact = copy.deepcopy(self.artifact)
        for field, value in (('name', 'image-bluefin-generic-123-2'), ('digest', None),
                             ('workflow_run', {'id': 123, 'head_sha': self.head})):
            self.artifact = {**original_artifact, field: value}
            with self.subTest(artifact_field=field), self.assertRaises(ValueError):
                self.invoke()
        self.assertFalse((self.root / '.bluebuild').exists())

    def test_cancelled_build_origin_is_not_successful_release_evidence(self):
        spec = importlib.util.spec_from_file_location('resume_release_gate', ROOT / 'scripts/bluebuild/release-evidence.py')
        release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release)
        self.run['conclusion'] = 'cancelled'
        self.metadata()
        with self.assertRaisesRegex(ValueError, 'successful matching main-branch'):
            release.validate_run(self.run, 'build.yml', self.source)

    def test_origin_run_cannot_be_foreign_untrusted_incomplete_or_another_workflow(self):
        original = copy.deepcopy(self.run)
        changes = {'id': 124, 'status': 'in_progress', 'conclusion': 'timed_out', 'event': 'pull_request',
                   'head_branch': 'feature', 'path': '.github/workflows/image.yml', 'head_sha': 'invalid',
                   'run_attempt': True, 'repository': {'full_name': 'attacker/finite'},
                   'head_repository': {'full_name': 'attacker/finite'}}
        for key, value in changes.items():
            self.run = {**original, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError): self.metadata()

    def test_source_and_image_jobs_must_succeed_in_same_attempt(self):
        original = copy.deepcopy(self.jobs)
        for index in range(len(original)):
            for key, value in (('conclusion', 'failure'), ('run_attempt', 2), ('head_sha', 'a' * 40)):
                self.jobs = copy.deepcopy(original)
                self.jobs[index][key] = value
                with self.subTest(index=index, key=key), self.assertRaises(ValueError): self.metadata()
        self.jobs = copy.deepcopy(original)
        self.jobs.append(copy.deepcopy(self.jobs[-1]))
        with self.assertRaises(ValueError): self.metadata()
        for step in range(4):
            self.jobs = copy.deepcopy(original)
            self.jobs[-1]['steps'][step]['conclusion'] = 'skipped'
            with self.assertRaises(ValueError): self.metadata()

    def test_artifact_attempt_digest_expiry_and_run_binding_are_required(self):
        original = copy.deepcopy(self.artifact)
        for key, value in (('expired', True), ('digest', None), ('size_in_bytes', 100000000),
                           ('name', 'image-bluefin-generic-123-2'),
                           ('workflow_run', {'id': 124, 'head_sha': self.source})):
            self.artifact = {**original, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError): self.metadata()

    def test_runtime_or_candidate_substitution_is_rejected(self):
        self.candidate()
        for key, value in (('buildIdentity', 'v1:' + 'a' * 64), ('revision', self.head),
                           ('sourceRevision', self.head), ('digest', 'sha256:' + 'a' * 64),
                           ('profile', 'bluefin-next'), ('publish', False), ('resumeOrigin', {})):
            original = self.record
            self.record = {**original, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError): self.candidate()
            self.record = original
        for key in self.info['Labels']:
            original = self.info['Labels'][key]
            self.info['Labels'][key] = 'substituted'
            with self.subTest(label=key), self.assertRaises(ValueError): self.candidate()
            self.info['Labels'][key] = original
        self.info['Digest'] = 'sha256:' + 'a' * 64
        with self.assertRaises(ValueError): self.candidate()

    def invoke(self, identity=None):
        def api(path, paginated=False):
            if '/jobs?' in path: return [{'jobs': self.jobs}]
            if '/artifacts?' in path: return [{'artifacts': [self.artifact]}]
            return self.run
        with patch.object(pub, 'github', side_effect=api), \
                patch.object(pub, 'origin_files', return_value=self.files), \
                patch.object(pub.upstream, 'image_identity', return_value=identity or self.identity), \
                patch.object(pub.upstream, 'verify') as authenticated, \
                patch.object(pub.upstream, 'inspect', side_effect=lambda image, **kw: self.info if '@' in image else None):
            pub.resume(self.profile, '123', self.digest, self.root)
            authenticated.assert_called_once_with(self.root)

    def test_policy_only_commit_resumes_original_digest_with_fresh_qualification_record(self):
        recipe_bytes = (self.root / 'recipes' / (self.profile + '.yml')).read_bytes()
        self.invoke()
        evidence = self.root / '.bluebuild'
        record = json.loads((evidence / (self.profile + '-publication.json')).read_text())
        self.assertEqual(record['revision'], self.head)
        self.assertEqual(record['sourceRevision'], self.source)
        self.assertTrue(record['qualify'])
        self.assertEqual(record['resumeOrigin']['digest'], self.digest)
        self.assertEqual((evidence / (self.profile + '-image-ref.txt')).read_text().strip(), self.image)
        self.assertEqual((self.root / 'recipes' / (self.profile + '.yml')).read_bytes(), recipe_bytes)
        self.assertFalse((evidence / (self.profile + '-acceptance.json')).exists())

    def test_changed_runtime_cannot_resume_and_emits_no_publication_record(self):
        with self.assertRaises(ValueError): self.invoke('v1:' + 'a' * 64)
        self.assertFalse((self.root / '.bluebuild').exists())

    def test_nonancestor_source_cannot_resume(self):
        self.git('checkout', '--orphan', 'unrelated')
        self.git('commit', '-m', 'Unrelated root')
        with patch.dict(os.environ, GITHUB_SHA=self.git('rev-parse', 'HEAD')):
            with self.assertRaises(subprocess.CalledProcessError): self.invoke()

    def test_entrypoint_rejects_nonmain_and_mutable_or_missing_inputs_before_api(self):
        for variable, value in (('GITHUB_REF', 'refs/heads/feature'), ('GITHUB_REPOSITORY', 'other/repo'),
                                ('GITHUB_EVENT_NAME', 'push')):
            with patch.dict(os.environ, {variable: value}), patch.object(pub, 'github') as api:
                with self.assertRaises(ValueError): pub.resume(self.profile, '123', self.digest, self.root)
                api.assert_not_called()
        with patch.object(pub, 'github') as api:
            for run, digest in ((None, self.digest), ('123', 'latest'), ('../123', self.digest)):
                with self.assertRaises(ValueError): pub.resume(self.profile, run, digest, self.root)
            api.assert_not_called()

    def test_archive_digest_and_named_contents_are_verified_without_extraction(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w') as archive:
            for name, content in self.files.items(): archive.writestr(name, content)
            archive.writestr('../../outside', 'never extracted')
        data = raw.getvalue()
        artifact = {**self.artifact, 'digest': 'sha256:' + hashlib.sha256(data).hexdigest()}
        def download(command, stdout, **kwargs): stdout.write(data)
        with patch.object(pub.subprocess, 'run', side_effect=download):
            self.assertEqual(pub.origin_files(artifact, self.profile), self.files)
            with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                pub.origin_files(self.artifact, self.profile)


class PromotionState(unittest.TestCase):
    def setUp(self):
        self.revision = 'a' * 40
        self.digest = 'sha256:' + 'b' * 64
        self.record = {'revision': self.revision, 'publishedDigest': self.digest,
                       'tags': ['finite', 'latest']}
        self.main = {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': self.revision}}

    def check(self, main=None, current=None):
        with patch.object(pub, 'github', return_value=self.main if main is None else main), \
                patch.object(pub.upstream, 'inspect', return_value=current):
            pub.promotion_state(self.record)

    def test_unchanged_main_and_primary_channel_are_required(self):
        with patch.object(pub, 'github', return_value=self.main) as api, \
                patch.object(pub.upstream, 'inspect', return_value={'Digest': self.digest}) as inspect:
            pub.promotion_state(self.record)
        api.assert_called_once_with('git/ref/heads/main')
        inspect.assert_called_once_with(pub.upstream.REPOSITORY + ':finite', allow_missing=True)

    def test_main_advancing_rejects_before_registry_read(self):
        advanced = {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': 'c' * 40}}
        with patch.object(pub, 'github', return_value=advanced), \
                patch.object(pub.upstream, 'inspect') as inspect:
            with self.assertRaisesRegex(ValueError, 'Main changed'):
                pub.promotion_state(self.record)
        inspect.assert_not_called()

    def comparison(self, paths):
        return {'status': 'ahead', 'base_commit': {'sha': self.revision},
                'merge_base_commit': {'sha': self.revision},
                'files': [{'filename': path, 'status': 'modified'} for path in paths]}

    def test_documentation_advance_preserves_qualification(self):
        advanced = {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': 'c' * 40}}
        comparison = self.comparison(['docs/evidence.json', 'CHANGELOG.md', '.great_cto/tasks.md'])
        with patch.object(pub, 'github', side_effect=[advanced, comparison, advanced]) as api, \
                patch.object(pub.upstream, 'inspect', return_value={'Digest': self.digest}):
            pub.promotion_state(self.record)
        self.assertEqual(api.call_args_list[1].args[0], f'compare/{self.revision}...{"c" * 40}')

    def test_release_inputs_still_require_requalification(self):
        for path in ('VERSION', 'cosign.pub', 'recipes/bluefin-generic.yml',
                     'scripts/bluebuild/vm-upgrade.py', 'automation/security/image-policy.json',
                     '.github/workflows/publication.yml', 'tests/bluebuild/resume.py'):
            with self.subTest(path=path), patch.object(pub, 'github', return_value=self.comparison([path])):
                self.assertFalse(pub.documentation_only_advance(self.revision, 'c' * 40))

    def test_unproven_comparisons_fail_closed(self):
        good = self.comparison(['docs/test.md'])
        cases = [[], {}, {**good, 'status': 'diverged'}, {**good, 'files': None}, {**good, 'merge_base_commit': None},
                 {**good, 'merge_base_commit': {'sha': 'd' * 40}},
                 self.comparison(['docs/file.md'] * 300),
                 self.comparison(['docs/../VERSION']),
                 {**good, 'files': [{'filename': 'docs/key.md', 'status': 'renamed',
                                   'previous_filename': 'cosign.pub'}]}]
        for comparison in cases:
            with self.subTest(comparison=comparison), patch.object(pub, 'github', return_value=comparison):
                self.assertFalse(pub.documentation_only_advance(self.revision, 'c' * 40))

    def test_main_moves_again_during_comparison(self):
        advanced = {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': 'c' * 40}}
        moved = {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': 'd' * 40}}
        with patch.object(pub, 'github', side_effect=[advanced, self.comparison(['README.md']), moved]), \
                patch.object(pub.upstream, 'inspect') as inspect:
            with self.assertRaisesRegex(ValueError, 'Main changed while'):
                pub.promotion_state(self.record)
        inspect.assert_not_called()

    def test_missing_or_malformed_main_reference_fails_closed(self):
        for response in ([], {}, {'ref': 'refs/heads/main', 'object': None},
                         {'ref': 'refs/heads/main', 'object': {'type': 'tag', 'sha': self.revision}},
                         {'ref': 'refs/heads/other', 'object': {'type': 'commit', 'sha': self.revision}}):
            with self.subTest(response=response), self.assertRaises(ValueError):
                self.check(main=response, current={'Digest': self.digest})

    def test_normal_channel_advance_or_disappearance_is_rejected(self):
        for current in ({'Digest': 'sha256:' + 'c' * 64}, None):
            with self.subTest(current=current), self.assertRaisesRegex(ValueError, 'Public channel changed'):
                self.check(current=current)

    def test_bootstrap_requires_channel_still_missing(self):
        self.record['publishedDigest'] = ''
        self.check(current=None)
        with self.assertRaisesRegex(ValueError, 'Public channel changed'):
            self.check(current={'Digest': self.digest})

    def test_resumed_candidate_cannot_overwrite_channel_after_fresh_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / '.bluebuild'
            evidence.mkdir()
            candidate = 'ghcr.io/closure-labs/finite@sha256:' + 'd' * 64
            source = 'e' * 40
            record = {**self.record, 'publish': True, 'profile': 'bluefin-generic',
                      'previousDigest': self.digest, 'recoveryReason': '', 'buildIdentity': 'v1:' + 'f' * 64,
                      'sourceRevision': source, 'qualificationMode': 'enforce', 'qualify': True,
                      'resumeOrigin': {'sourceRevision': source, 'digest': candidate.split('@')[1]}}
            acceptance = {'accepted': True, 'candidate': candidate, 'previousDigest': self.digest,
                          'profile': record['profile'], 'revision': self.revision, 'sourceRevision': source,
                          'buildIdentity': record['buildIdentity'], 'secureBoot': True, 'encryptedRoot': True}
            (evidence / 'bluefin-generic-publication.json').write_text(json.dumps(record))
            (evidence / 'bluefin-generic-image-ref.txt').write_text(candidate + '\n')
            (evidence / 'bluefin-generic-acceptance.json').write_text(json.dumps(acceptance))
            with patch.dict(os.environ, GITHUB_SHA=self.revision, FINITE_QUALIFICATION_MODE='enforce'), \
                    patch.object(pub, 'github', return_value=self.main), \
                    patch.object(pub.upstream, 'inspect', return_value={'Digest': 'sha256:' + 'c' * 64}), \
                    patch.object(pub.security, 'verify') as security, \
                    patch.object(pub.desktop, 'verify'), \
                    patch.object(pub.subprocess, 'run') as command:
                with self.assertRaisesRegex(ValueError, 'Public channel changed'):
                    pub.promote('bluefin-generic', root)
            security.assert_called_once()
            self.assertEqual(command.call_count, 1)
            self.assertEqual(command.call_args.args[0][:2], ['cosign', 'verify'])
            self.assertFalse((evidence / 'bluefin-generic-promoted.json').exists())


if __name__ == '__main__':
    unittest.main()
