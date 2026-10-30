#!/usr/bin/env python3
"""The optional builder cannot silently omit a recipe or become a publisher."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'experiments/containerfile' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load('prepare')
configuration = load('image-config')


class Contract(unittest.TestCase):
    def tree(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for directory in ('experiments/containerfile', 'recipes', 'sources', 'files/scripts', 'scripts/ci', 'scripts/bluebuild'):
            shutil.copytree(ROOT / directory, root / directory, ignore=shutil.ignore_patterns('__pycache__'))
        return root

    def test_hermetic_workflow_lint_includes_experimental_script(self):
        declaration = (ROOT / 'lib/check-sources.nix').read_text()
        workflow = next(line for line in declaration.splitlines() if 'workflow-lint = source' in line)
        self.assertIn('../experiments/containerfile/build.sh', workflow)

    def provenance(self, source):
        return {'foundationSource': source, 'foundationSourceSha256': '1' * 64,
                'fzf': {'path': '/usr/bin/fzf', 'resolvedPath': '/usr/bin/fzf',
                        'sha256': '2' * 64, 'owner': 'fzf\t0\t0.65.2\t1.fc44\tx86_64\n'}}

    def test_foundation_lock_and_release_metadata_must_agree(self):
        expected = prepare.foundation_source()
        self.assertEqual(expected['rev'], json.loads((ROOT / 'sources/foundation.json').read_text())['rev'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sources').mkdir()
            shutil.copy2(ROOT / 'flake.lock', root / 'flake.lock')
            source = json.loads((ROOT / 'sources/foundation.json').read_text())
            source['rev'] = 'a' * 40
            (root / 'sources/foundation.json').write_text(json.dumps(source))
            with self.assertRaisesRegex(ValueError, 'differs from the lock'):
                prepare.foundation_source(root)

    def test_installed_provenance_rejects_stale_foundation_and_nonstock_fzf(self):
        expected = prepare.foundation_source()
        observed = self.provenance(expected)
        packages, _ = prepare.rpm_inventory(observed['fzf']['owner'])
        receipt = prepare.validate_provenance(observed, expected, packages)
        self.assertEqual(receipt['fzf']['owner']['name'], 'fzf')
        for key in expected:
            stale = copy.deepcopy(observed)
            stale['foundationSource'][key] = 'wrong'
            with self.assertRaisesRegex(ValueError, 'exact lock source'):
                prepare.validate_provenance(stale, expected, packages)
        for field, value in [('path', '/home/linuxbrew/.linuxbrew/bin/fzf'),
                             ('resolvedPath', '/home/linuxbrew/.linuxbrew/bin/fzf'),
                             ('owner', 'other\t0\t0.65.2\t1.fc44\tx86_64\n'),
                             ('sha256', 'invalid')]:
            wrong = copy.deepcopy(observed)
            wrong['fzf'][field] = value
            with self.assertRaises(ValueError):
                prepare.validate_provenance(wrong, expected, packages)
        with self.assertRaisesRegex(ValueError, 'inventoried fzf RPM'):
            prepare.validate_provenance(observed, expected, [])

    def test_current_recipes_are_supported(self):
        recipes, _, _ = prepare.contract()
        self.assertEqual(recipes['recipes/finite-dev.yml']['base-image'], 'ghcr.io/ublue-os/bluefin-dx')

    def test_every_recipe_change_requires_review(self):
        root = self.tree()
        for name in ('finite.yml', 'finite-dev.yml', 'shared/base.yml', 'shared/final.yml'):
            path = root / 'recipes' / name
            original = path.read_text()
            document = yaml.safe_load(original)
            document['modules'].append({'type': 'script@v1', 'scripts': ['unreviewed.sh']})
            path.write_text(yaml.safe_dump(document))
            with self.assertRaisesRegex(ValueError, 'Recipe drift'):
                prepare.contract(root)
            path.write_text(original)

    def test_floating_base_and_mismatched_tools_rejected(self):
        root = self.tree()
        path = root / 'recipes/finite.yml'
        original = yaml.safe_load(path.read_text())
        for key, value in [('image-version', 'stable'), ('cosign-version', 'latest')]:
            document = copy.deepcopy(original)
            document[key] = value
            path.write_text(yaml.safe_dump(document))
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                prepare.contract(root)

    def test_digest_refresh_is_not_a_second_configuration_owner(self):
        root = self.tree()
        path = root / 'recipes/finite.yml'
        document = yaml.safe_load(path.read_text())
        document['image-version'] = 'stable@sha256:' + 'a' * 64
        path.write_text(yaml.safe_dump(document))
        self.assertEqual(prepare.contract(root)[0]['recipes/finite.yml']['image-version'], document['image-version'])

    def test_full_build_requires_explicit_branch_dispatch(self):
        for values in ({}, {'GITHUB_EVENT_NAME': 'pull_request'},
                       {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REPOSITORY': 'closure-labs/finite', 'GITHUB_REF': 'refs/heads/main'}):
            with patch.dict('os.environ', values, clear=True), self.assertRaises(ValueError):
                prepare.build({})

    def test_pr_opt_in_is_exact_and_rejects_forks_and_wrong_event(self):
        repository = {'full_name': 'closure-labs/finite', 'fork': False}
        payload = {'number': 321, 'action': 'synchronize', 'repository': repository,
                   'pull_request': {'number': 321,
                                    'head': {'repo': repository, 'ref': 'codex/explore-containerfile', 'sha': 'a' * 40},
                                    'base': {'ref': 'main', 'repo': repository}}}
        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory) / 'event.json'
            env = {'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_REPOSITORY': 'closure-labs/finite',
                   'GITHUB_REF': 'refs/pull/321/merge', 'GITHUB_EVENT_PATH': str(event)}
            with patch.dict('os.environ', env, clear=True):
                event.write_text(json.dumps(payload))
                self.assertEqual(prepare.authorized_revision(), 'a' * 40)
                changes = [('number', 322), ('action', 'labeled'),
                           ('pull_request.head.repo.fork', True),
                           ('pull_request.head.repo.full_name', 'other/finite'),
                           ('pull_request.head.ref', 'main'), ('pull_request.head.sha', 'latest'),
                           ('pull_request.base.ref', 'other')]
                for field, value in changes:
                    wrong = copy.deepcopy(payload)
                    cursor = wrong
                    parts = field.split('.')
                    for part in parts[:-1]:
                        cursor = cursor[part]
                    cursor[parts[-1]] = value
                    event.write_text(json.dumps(wrong))
                    with self.assertRaises(ValueError, msg=field):
                        prepare.authorized_revision()
                event.write_text(json.dumps(payload))
                for key, value in [('GITHUB_EVENT_NAME', 'pull_request_target'),
                                   ('GITHUB_REPOSITORY', 'other/finite'), ('GITHUB_REF', 'refs/pull/322/merge')]:
                    with patch.dict('os.environ', {key: value}), self.assertRaises(ValueError):
                        prepare.authorized_revision()

    def test_no_publication_or_shared_image_workflow(self):
        workflow = (ROOT / '.github/workflows/containerfile-experiment.yml').read_text()
        self.assertIn('contents: read', workflow)
        self.assertNotIn('write', workflow)
        self.assertNotIn('secrets.', workflow)
        for forbidden in ('publication.yml', 'qualification.yml', 'iso.yml', '--push', 'cosign sign'):
            self.assertNotIn(forbidden, workflow)
        source = (ROOT / 'experiments/containerfile/prepare.py').read_text()
        self.assertIn("'--load'", source)
        self.assertNotIn("'--push'", source)
        self.assertIn("'containerfile-v1:'", source)

    def test_all_integration_scripts_remain_in_order(self):
        script = (ROOT / 'experiments/containerfile/build.sh').read_text()
        sequence = ['check-upstream-kernel snapshot', 'scripts/nix-identities.sh', 'dnf -y install',
                    'scripts/security-remediate.py', 'scripts/tailscale-security.py',
                    'image-config.py payload', 'scripts/nix-install.sh', 'scripts/authselect.sh',
                    'systemctl -f enable', 'systemctl --global -f enable', 'scripts/profile.sh',
                    '--no-hostonly --reproducible', 'check-upstream-kernel verify',
                    'image-config.py identity', 'scripts/finalize.sh', 'bash /ctx/verify-image.sh']
        positions = [script.index(token) for token in sequence]
        self.assertEqual(positions, sorted(positions))

    def test_build_uses_exact_base_and_rejects_wrong_output_identity(self):
        plan = {'profile': 'finite', 'foundation': 'bluefin',
                'baseImage': 'ghcr.io/ublue-os/bluefin', 'baseDigest': 'sha256:' + 'a' * 64,
                'cosignImage': 'cosign@sha256:' + 'b' * 64,
                'bluebuildImage': 'cli@sha256:' + 'c' * 64,
                'sourceRevision': 'd' * 40, 'referenceIdentity': 'v1:reference',
                'created': '2026-10-29T02:00:00Z', 'version': 'containerfile-dddddddddddd',
                'description': 'unpublished experiment', 'url': 'https://github.com/closure-labs/finite',
                'experimentIdentity': 'containerfile-v1:experiment',
                'foundationSource': prepare.foundation_source()}
        labels = {'io.finite.build-inputs': plan['experimentIdentity'],
                  'io.finite.reference-build-inputs': plan['referenceIdentity'],
                  'org.opencontainers.image.revision': plan['sourceRevision'],
                  'org.opencontainers.image.base.digest': plan['baseDigest'],
                  'org.opencontainers.image.base.name': plan['baseImage'],
                  'org.opencontainers.image.created': plan['created'],
                  'org.opencontainers.image.version': plan['version'],
                  'org.opencontainers.image.description': plan['description'],
                  'org.opencontainers.image.url': plan['url'],
                  'io.finite.profile': 'finite', 'io.finite.foundation': 'bluefin',
                  'io.finite.production-eligible': 'false'}
        env = {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REPOSITORY': 'closure-labs/finite',
               'GITHUB_REF': 'refs/heads/experiment', 'SOURCE_DATE_EPOCH': '123',
               'GITHUB_SHA': plan['sourceRevision']}
        with patch.dict('os.environ', dict(env, GITHUB_SHA='e' * 40), clear=True):
            with self.assertRaisesRegex(ValueError, 'Prepared plan differs'):
                prepare.build(plan)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.bluebuild/containerfile').mkdir(parents=True)
            for path in ('files', 'experiments/containerfile', 'scripts/bluebuild', '.git'):
                (root / path).mkdir(parents=True, exist_ok=True)
            for path in ('cosign.pub', '.bluebuild/containerfile/plan.json', 'scripts/bluebuild/verify-image.sh'):
                (root / path).write_text('fixture')
            (root / '.git/config').write_text('credential must not enter context')
            contexts = []
            def inspect_context(command, **kwargs):
                if command[:3] == ['docker', 'buildx', 'build']:
                    context = Path(command[-1])
                    contexts.append(sorted(str(p.relative_to(context)) for p in context.rglob('*')))
                    self.assertFalse((context / '.git').exists())
                    self.assertFalse((context / '.github').exists())
                    self.assertTrue((context / 'cosign.pub').exists())
            def output(command, **kwargs):
                if command[:3] == ['docker', 'image', 'inspect']:
                    return json.dumps([{'Id': 'sha256:' + 'f' * 64, 'Config': {'Labels': labels}}])
                self.assertIn('--network=none', command)
                self.assertIn('sha256:' + 'f' * 64, command)
                if 'python3' in command:
                    self.assertIn(prepare.PROVENANCE_QUERY, command)
                    return json.dumps(self.provenance(plan['foundationSource']))
                self.assertIn('rpm', command)
                return 'nix\t0\t2.30.1\t1.fc44\tx86_64\nfzf\t0\t0.65.2\t1.fc44\tx86_64\n'
            with patch.dict('os.environ', env, clear=True), patch.object(prepare.subprocess, 'run', side_effect=inspect_context) as run, patch.object(
                    prepare.subprocess, 'check_output', side_effect=output):
                prepare.build(plan, root)
                command = run.call_args_list[0].args[0]
                self.assertIn('BASE_IMAGE=' + plan['baseImage'] + '@' + plan['baseDigest'], command)
                self.assertIn('--load', command)
                self.assertNotIn('--push', command)
                self.assertNotIn('SOURCE_DATE_EPOCH', run.call_args_list[0].kwargs['env'])
                self.assertIn('--network=none', run.call_args_list[1].args[0])
                self.assertIn('sha256:' + 'f' * 64, run.call_args_list[1].args[0])
                receipt = json.loads((root / '.bluebuild/containerfile/rpm-inventory.json').read_text())
                self.assertEqual(receipt['imageId'], 'sha256:' + 'f' * 64)
                self.assertEqual(receipt['packageCount'], 2)
                self.assertEqual(receipt['sourceRevision'], plan['sourceRevision'])
                provenance = json.loads((root / '.bluebuild/containerfile/installed-provenance.json').read_text())
                self.assertEqual(provenance['imageId'], receipt['imageId'])
                self.assertEqual(provenance['foundationSource'], plan['foundationSource'])
                self.assertFalse(provenance['userSessionValidated'])
                for key in labels:
                    wrong = dict(labels)
                    wrong[key] = 'wrong'
                    with patch.object(prepare.subprocess, 'check_output', return_value=json.dumps([{'Id': 'sha256:' + 'f' * 64, 'Config': {'Labels': wrong}}])):
                        with self.assertRaisesRegex(ValueError, 'labels do not match'):
                            prepare.build(plan, root)

    def test_rpm_inventory_is_sorted_hashed_and_rejects_incomplete_records(self):
        first = 'zlib\t0\t1.3.1\t1.fc44\tx86_64\n'
        second = 'nix\t1\t2.30.1\t1.fc44\tx86_64\n'
        packages, digest = prepare.rpm_inventory(first + second)
        self.assertEqual(packages[0]['name'], 'nix')
        self.assertEqual(prepare.rpm_inventory(second + first + first), (packages, digest))
        self.assertNotEqual(prepare.rpm_inventory((first + second).replace('x86_64', 'aarch64'))[1], digest)
        for invalid in ('', 'nix\t2.30\tx86_64', 'nix\tunknown\t2.30\t1\tx86_64'):
            with self.assertRaises(ValueError):
                prepare.rpm_inventory(invalid)

    def test_cleanup_retains_old_hidden_entry_semantics(self):
        script = (ROOT / 'experiments/containerfile/build.sh').read_text()
        cleanup = next(line for line in script.splitlines() if line.startswith('find /var '))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mutable = root / 'var'
            mutable.mkdir()
            (mutable / 'cache').mkdir()
            (mutable / 'cache/item').touch()
            (mutable / '.hidden').touch()
            outside = root / 'keep'
            outside.write_text('untouched')
            (mutable / 'link').symlink_to(outside)
            subprocess.run(['bash', '-c', cleanup.replace('find /var ', 'find "' + str(mutable) + '" ', 1)], check=True)
            self.assertEqual(sorted(path.name for path in mutable.iterdir()), ['.hidden'])
            self.assertEqual(outside.read_text(), 'untouched')

    def test_payload_preserves_symlinks_and_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ctx = root / 'ctx'
            (ctx / 'files/payload/home').mkdir(parents=True)
            source = ctx / 'files/payload/home/activate'
            source.write_text('example')
            (source.parent / '.gitkeep').touch()
            source.chmod(0o755)
            (source.parent / 'link').symlink_to('activate')
            (ctx / 'plan.json').write_text(json.dumps({'copies': [
                {'source': 'payload/home', 'destination': '/usr/share/finite/home'}]}))
            configuration.payload(ctx, root)
            target = root / 'usr/share/finite/home'
            self.assertFalse((target / '.gitkeep').exists())
            self.assertEqual((target / 'activate').stat().st_mode & 0o777, 0o755)
            self.assertEqual((target / 'link').readlink(), Path('activate'))

    def test_os_identity_and_signature_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ctx = root / 'ctx'
            ctx.mkdir()
            (ctx / 'experiment').mkdir()
            shutil.copy2(ROOT / 'experiments/containerfile/signing-policy.json', ctx / 'experiment/signing-policy.json')
            (ctx / 'cosign.pub').write_text('test public key')
            (ctx / 'plan.json').write_text(json.dumps({'osRelease': {'NAME': 'Finite', 'PRETTY_NAME': 'Finite'}}))
            (root / 'etc/containers').mkdir(parents=True)
            (root / 'etc/os-release').write_text('NAME="Bluefin"\nID=fedora\nVERSION_ID=44\n')
            inherited = {'default': [{'type': 'reject'}], 'transports': {'docker': {'upstream.example': [{'type': 'reject'}]}}}
            (root / 'etc/containers/policy.json').write_text(json.dumps(inherited))
            configuration.identity(ctx, root)
            result = (root / 'etc/os-release').read_text()
            self.assertIn('NAME="Finite"', result)
            self.assertIn('ID=fedora\nVERSION_ID=44', result)
            policy = json.loads((root / 'etc/containers/policy.json').read_text())
            self.assertEqual(policy['default'], inherited['default'])
            self.assertEqual(policy['transports']['docker']['upstream.example'], [{'type': 'reject'}])
            finite = policy['transports']['docker']['ghcr.io/closure-labs/finite'][0]
            self.assertEqual(finite['type'], 'sigstoreSigned')
            self.assertEqual(finite['signedIdentity'], {'type': 'matchRepository'})
            self.assertEqual((root / finite['keyPath'].lstrip('/')).read_text(), 'test public key')



class HostedVM(unittest.TestCase):
    def setUp(self):
        self.vm = load('validate-vm')
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / '.bluebuild/containerfile'
        self.directory.mkdir(parents=True)
        self.revision = 'a' * 40
        self.image = 'sha256:' + 'b' * 64
        self.plan = {'sourceRevision': self.revision, 'profile': 'finite',
                     'experimentIdentity': 'containerfile-v1:' + 'c' * 64,
                     'baseDigest': 'sha256:' + 'd' * 64, 'foundationSource': {'rev': 'e' * 40}}
        self.receipt = {**self.plan, 'imageId': self.image}
        self.info = {'Id': self.image, 'Config': {'Labels': {
            'io.finite.production-eligible': 'false', 'io.finite.build-inputs': self.plan['experimentIdentity'],
            'org.opencontainers.image.revision': self.revision, 'io.finite.profile': 'finite',
            'org.opencontainers.image.base.digest': self.plan['baseDigest']}}}

    def invoke(self, status=0, revision=None):
        (self.directory / 'plan.json').write_text(json.dumps(self.plan))
        (self.directory / 'installed-provenance.json').write_text(json.dumps(self.receipt))
        with patch.dict('os.environ', {'GITHUB_ACTIONS': 'true', 'GITHUB_EVENT_NAME': 'pull_request'}), \
                patch.object(self.vm.prepare, 'authorized_revision', return_value=self.revision), \
                patch.object(self.vm.subprocess, 'check_output', side_effect=[revision or self.revision, json.dumps([self.info])]), \
                patch.object(self.vm.subprocess, 'run', return_value=subprocess.CompletedProcess([], status)) as run:
            result = self.vm.validate(self.root)
            return result, run

    def test_verified_image_uses_existing_unsigned_harness_and_actual_head(self):
        result, run = self.invoke()
        self.assertEqual(result, 0)
        self.assertEqual(run.call_args.args[0], ['bash', 'scripts/bluebuild/local-vm.sh', 'finite'])
        self.assertEqual(run.call_args.kwargs['env']['GITHUB_SHA'], self.revision)
        self.assertEqual((self.root / '.bluebuild/finite-image-ref.txt').read_text().strip(), self.image)
        outcome = json.loads((self.directory / 'vm-result.json').read_text())
        self.assertFalse(outcome['authorizesPublication'])
        self.assertEqual(outcome['imageId'], self.image)

    def test_failure_exit_status_is_preserved_and_recorded(self):
        result, _ = self.invoke(status=17)
        self.assertEqual(result, 17)
        self.assertEqual(json.loads((self.directory / 'vm-result.json').read_text())['exitCode'], 17)

    def test_stale_receipt_and_production_identity_rejected(self):
        for field, value in [('sourceRevision', 'f' * 40), ('imageId', 'mutable:tag'),
                             ('experimentIdentity', 'production'), ('foundationSource', {})]:
            with self.subTest(field=field):
                old = self.receipt[field]
                self.receipt[field] = value
                with self.assertRaises(ValueError):
                    self.invoke()
                self.receipt[field] = old
        self.info['Config']['Labels']['io.finite.production-eligible'] = 'true'
        with self.assertRaises(ValueError):
            self.invoke()

    def test_wrong_checkout_and_non_pr_execution_rejected(self):
        with self.assertRaises(ValueError):
            self.invoke(revision='f' * 40)
        for event in ('push', 'workflow_dispatch', 'merge_group'):
            with patch.dict('os.environ', {'GITHUB_ACTIONS': 'true', 'GITHUB_EVENT_NAME': event}), self.assertRaises(ValueError):
                self.vm.validate(self.root)


if __name__ == '__main__':
    unittest.main()
