#!/usr/bin/env python3
"""Native archive equivalence, adversarial transport, and workflow contracts."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('shared_payload', ROOT / 'scripts/bluebuild/shared-payload.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Archive(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.runtime = 'a' * 32 + '-runtime'
        files = {'home-manager-template/config.nix': b'{ ... }: {}\n',
                 'nix-runtime/runtime.json': b'{"schema":1}\n',
                 'nix-runtime/registration': b'registration\x00\xff',
                 'nix-runtime/store/' + self.runtime + '/bin/nix': b'native binary\x00\xff'}
        for name, data in files.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(0o555 if path.name == 'nix' else 0o444)
        (self.source / ('nix-runtime/store/' + self.runtime + '/bin/nix-store')).symlink_to('nix')
        (self.source / 'native-link').symlink_to('/nix/store/' + self.runtime + '/bin/nix')
        self.env = {'GITHUB_REPOSITORY': 'closure-labs/finite', 'GITHUB_SHA': 'a' * 40,
                    'GITHUB_RUN_ID': '1234', 'GITHUB_RUN_ATTEMPT': '2'}
        self.archive = self.root / 'payload.tar'
        self.result = m.create(self.source, self.archive, self.env)
        self.destination = self.root / 'files/payload'

    def stage(self, **values):
        args = {'archive': self.archive, 'sha': self.result['sha256'], 'revision': self.env['GITHUB_SHA'],
                'run': self.env['GITHUB_RUN_ID'], 'attempt': self.env['GITHUB_RUN_ATTEMPT'],
                'artifact_id': '5678', 'destination': self.destination, 'env': self.env}
        return m.stage(**{**args, **values})

    def rewrite(self, changes=None, extra=(), context=None):
        path = self.root / 'mutated.tar'
        with tarfile.open(self.archive) as original, tarfile.open(path, 'w') as changed:
            for member in original:
                data = original.extractfile(member).read() if member.isreg() else b''
                if member.name == './context.json' and context is not None:
                    data = context
                    member.size = len(data)
                if changes:
                    changes(member)
                changed.addfile(member, io.BytesIO(data) if member.isreg() else None)
            for member, data in extra:
                changed.addfile(member, io.BytesIO(data) if member.isreg() else None)
        return path

    def blocked_before_extract(self, path=None, **values):
        path = path or self.archive
        with path.open('rb') as stream:
            sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        self.destination.mkdir(parents=True, exist_ok=True)
        sentinel = self.destination / 'existing'
        sentinel.write_bytes(b'preserve existing staging on failure')
        before = set(self.destination.rglob('*'))
        with patch.object(m.subprocess, 'run', side_effect=AssertionError('No extraction may start')):
            with self.assertRaises((ValueError, tarfile.TarError, OSError)):
                self.stage(archive=path, **{'sha': sha, **values})
        self.assertEqual(set(self.destination.rglob('*')), before)
        self.assertEqual(sentinel.read_bytes(), b'preserve existing staging on failure')

    def test_matches_direct_cp_staging_files_modes_and_symlinks(self):
        direct = self.root / 'direct'
        subprocess.run(['cp', '-a', str(self.source), str(direct)], check=True)
        subprocess.run(['chmod', '-R', 'u+w', str(direct)], check=True)
        result = self.stage()
        self.assertEqual(result['artifactId'], '5678')
        self.assertEqual(result['consumerAttempt'], '2')
        self.assertEqual({p.relative_to(direct) for p in direct.rglob('*')},
                         {p.relative_to(self.destination) for p in self.destination.rglob('*')})
        for original in direct.rglob('*'):
            restored = self.destination / original.relative_to(direct)
            if original.is_symlink():
                self.assertTrue(restored.is_symlink())
                self.assertEqual(os.readlink(original), os.readlink(restored))
            elif original.is_file():
                self.assertEqual(original.read_bytes(), restored.read_bytes())
            self.assertEqual(stat.S_IMODE(original.lstat().st_mode), stat.S_IMODE(restored.lstat().st_mode))

    def test_same_artifact_stages_both_profiles_without_nix(self):
        first = self.stage()
        second = self.stage(destination=self.root / 'dev/payload')
        self.assertEqual(first, second)

    def test_carried_successful_producer_attempt_is_explicit_not_relabelled(self):
        older = {**self.env, 'GITHUB_RUN_ATTEMPT': '1'}
        self.result = m.create(self.source, self.archive, older)
        result = self.stage(attempt='1')
        self.assertEqual(result['runAttempt'], '1')
        self.assertEqual(result['consumerAttempt'], '2')
        self.blocked_before_extract(attempt='2')

    def test_missing_malformed_stale_and_future_native_outputs_fail_before_extract(self):
        for field, values in {'sha': ['', 'x'*64, '0'*64], 'artifact_id': ['', '0', '1,2', '../1'],
                              'attempt': ['', '0', '3', '02', '٢'], 'run': ['', '1235'],
                              'revision': ['', 'b'*40]}.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.blocked_before_extract(**{field: value})

    def test_missing_linked_and_corrupt_archive_fail_before_extract(self):
        self.blocked_before_extract(sha='0'*64)
        missing = self.root/'absent.tar'
        with self.assertRaises(ValueError): self.stage(archive=missing)
        linked = self.root/'linked.tar'; linked.symlink_to(self.archive)
        self.blocked_before_extract(linked)
        malformed = self.root/'bad.tar'; malformed.write_bytes(b'not a tar archive')
        self.blocked_before_extract(malformed)

    def test_context_binds_every_field_and_rejects_duplicates_or_wrong_schema(self):
        original = m.context(self.env)
        for field, value in [('revision', 'b'*40), ('repository', 'elsewhere/repo'),
                             ('runId', '1235'), ('runAttempt', '1'), ('schema', True)]:
            with self.subTest(field=field):
                data = json.dumps({**original, field: value}).encode()
                self.blocked_before_extract(self.rewrite(context=data))
        raw = json.dumps(original).replace('"schema": 1', '"schema": 1, "schema": 1').encode()
        self.blocked_before_extract(self.rewrite(context=raw))

    def test_absent_and_oversized_context_fail_before_extract(self):
        self.blocked_before_extract(self.rewrite(lambda member: setattr(member, 'name', './payload/context-hidden')
                                                if member.name == './context.json' else None))
        self.blocked_before_extract(self.rewrite(context=b'x'*16385))

    def test_archive_expanded_size_and_member_limits(self):
        with patch.object(m, 'MAX_BYTES', 1): self.blocked_before_extract()
        with patch.object(m, 'MAX_MEMBERS', 2): self.blocked_before_extract()
        with tarfile.open(self.archive) as archive, patch.object(m, 'MAX_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'expanded size'): m.members(archive, m.context(self.env))

    def test_duplicate_path_traversal_absolute_and_foreign_root_fail(self):
        for name in ('./context.json', '../escape', '/tmp/escape', 'payload/../escape',
                     'payload//escape', 'payload/./escape', 'other/escape', 'payload\\escape'):
            with self.subTest(name=name):
                extra = tarfile.TarInfo(name); extra.size = 1
                self.blocked_before_extract(self.rewrite(extra=[(extra, b'x')]))

    def test_symlink_escape_dangling_and_missing_closure_target_fail(self):
        for target in ('../../escape', '/etc/passwd', 'missing', '/nix/store/missing/bin/nix'):
            with self.subTest(target=target):
                extra = tarfile.TarInfo('payload/link'); extra.type = tarfile.SYMTYPE; extra.linkname = target
                self.blocked_before_extract(self.rewrite(extra=[(extra, b'')]))

    def test_linked_parent_hardlink_special_node_and_privileged_mode_fail(self):
        link = tarfile.TarInfo('payload/linked'); link.type = tarfile.SYMTYPE; link.linkname = 'home-manager-template'
        child = tarfile.TarInfo('payload/linked/child'); child.size = 1
        self.blocked_before_extract(self.rewrite(extra=[(link,b''), (child,b'x')]))
        for kind in (tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE):
            extra = tarfile.TarInfo('payload/special'); extra.type = kind
            extra.linkname = 'payload/nix-runtime/registration'
            self.blocked_before_extract(self.rewrite(extra=[(extra,b'')]))
        extra = tarfile.TarInfo('payload/privileged'); extra.mode = 0o4755
        self.blocked_before_extract(self.rewrite(extra=[(extra,b'')]))

    def test_root_and_payload_must_be_directories(self):
        for name in ('.', './payload'):
            def change(member):
                if member.name == name:
                    member.type = tarfile.SYMTYPE; member.linkname = 'payload/home-manager-template'
            self.blocked_before_extract(self.rewrite(change))

    def test_linked_staging_destination_or_parent_fails(self):
        outside = self.root/'outside'; outside.mkdir()
        self.destination.parent.mkdir(); self.destination.symlink_to(outside)
        with self.assertRaises(ValueError): self.stage()
        self.destination.unlink(); self.destination.parent.rmdir()
        self.destination.parent.symlink_to(outside)
        with self.assertRaises(ValueError): self.stage()
        self.assertEqual(list(outside.iterdir()), [])

    def test_invalid_repository_or_env_never_stages(self):
        for field in self.env:
            with self.subTest(field=field):
                env = {**self.env, field: ''}
                self.blocked_before_extract(env=env)

    def test_cli_preflight_rejects_missing_outputs_without_reading_archive(self):
        command = ['python3', str(ROOT/'scripts/bluebuild/shared-payload.py'), 'validate',
                   '--sha256', self.result['sha256'], '--revision', self.env['GITHUB_SHA'],
                   '--run', self.env['GITHUB_RUN_ID'], '--attempt', '2', '--artifact-id']
        good = subprocess.run([*command, '5678'], env={**os.environ, **self.env}, capture_output=True)
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertEqual(json.loads(good.stdout), m.context(self.env))
        bad = subprocess.run([*command, ''], env={**os.environ, **self.env}, capture_output=True)
        self.assertNotEqual(bad.returncode, 0)
        self.assertFalse(self.destination.exists())

    def test_pax_metadata_is_not_a_second_extraction_dialect(self):
        path = self.root/'pax.tar'
        with tarfile.open(self.archive) as original, tarfile.open(path, 'w', format=tarfile.PAX_FORMAT) as changed:
            for member in original:
                if member.name == './payload/nix-runtime/registration':
                    member.pax_headers = {'mtime': '1234.5'}
                data = original.extractfile(member).read() if member.isreg() else b''
                changed.addfile(member, io.BytesIO(data) if member.isreg() else None)
        self.blocked_before_extract(path)


def workflow(name):
    return yaml.safe_load((ROOT / '.github/workflows' / (name + '.yml')).read_text())


class Wiring(unittest.TestCase):
    def test_one_producer_and_both_consumers_share_exact_native_outputs(self):
        jobs = workflow('build')['jobs']
        producer = jobs['payload']
        self.assertEqual(producer['needs'], ['impact', 'docs', 'checks'])
        self.assertEqual(producer['permissions'], {'contents': 'read'})
        self.assertNotIn('secrets', producer)
        for name in ('images', 'publish'):
            self.assertIn('payload', jobs[name]['needs'])
            for key in ('artifact_id', 'sha256', 'revision', 'run', 'attempt'):
                self.assertEqual(jobs[name]['with']['payload_'+key], '${{ needs.payload.outputs.'+key+' }}')
        self.assertIn('payload', jobs['gate']['needs'])
        for name in ('images', 'publish'):
            self.assertFalse(jobs[name]['strategy']['fail-fast'])
            self.assertEqual(jobs[name]['permissions']['actions'], 'read')
        self.assertEqual(jobs['images']['with']['vm_validation'], "${{ needs.impact.outputs.vm == 'true' }}")

    def test_pr_no_images_and_resume_skip_new_compilation(self):
        producer = workflow('build')['jobs']['payload']
        for condition in ("needs.checks.outputs.images == 'true'", "github.event_name != 'pull_request'",
                          "(inputs.resume_run || '') == ''", "(inputs.resume_digest || '') == ''"):
            self.assertIn(condition, producer['if'])
        publish = workflow('build')['jobs']['publish']
        for condition in ("!cancelled()", "needs.payload.result == 'success'", "needs.payload.result == 'skipped'",
                          "needs.checks.result == 'success'", "needs.impact.result == 'success'", "needs.docs.result == 'success'"):
            self.assertIn(condition, publish['if'])

    def test_publication_forwards_all_inputs_and_validation_precedes_download(self):
        for key in ('artifact_id', 'sha256', 'revision', 'run', 'attempt'):
            self.assertEqual(workflow('publication')['jobs']['build']['with']['payload_'+key],
                             '${{ inputs.payload_'+key+' }}')
        steps = workflow('image')['jobs']['build']['steps']
        validate = next(s for s in steps if s.get('name', '').startswith('Validate same-run payload'))
        download = next(s for s in steps if s.get('uses', '').startswith('actions/download-artifact@'))
        stage = next(s for s in steps if s.get('name') == 'Stage pinned payload')
        setup = next(s for s in steps if s.get('uses') == '$/.github/actions/setup-nix')
        self.assertLess(steps.index(validate), steps.index(setup))
        self.assertLess(steps.index(validate), steps.index(download))
        self.assertLess(steps.index(download), steps.index(stage))
        self.assertEqual(download['with']['artifact-ids'], '${{ inputs.payload_artifact_id }}')
        self.assertEqual(download['with']['run-id'], '${{ github.run_id }}')
        self.assertEqual(download['with']['github-token'], '${{ github.token }}')
        for step in (validate, download, stage):
            self.assertEqual(step['if'], "inputs.resume_run == '' && inputs.resume_digest == ''")
            self.assertNotIn('continue-on-error', step)
        self.assertNotIn('nix build', stage['run'])
        self.assertIn('nix build', (ROOT/'scripts/bluebuild/stage.sh').read_text())
        retain = next(s for s in steps if s.get('name') == 'Save build evidence')
        self.assertIn('!.bluebuild/shared-payload/**', retain['with']['path'])
        self.assertIn('.bluebuild/shared-payload.json', stage['run'])


if __name__ == '__main__':
    unittest.main()
