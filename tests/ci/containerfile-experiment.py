#!/usr/bin/env python3
"""The optional builder cannot silently omit a recipe or become a publisher."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
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
            with patch.dict('os.environ', values, clear=True), self.assertRaisesRegex(ValueError, 'explicit dispatch'):
                prepare.build({})

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
                'experimentIdentity': 'containerfile-v1:experiment'}
        labels = {'io.finite.build-inputs': plan['experimentIdentity'],
                  'io.finite.reference-build-inputs': plan['referenceIdentity'],
                  'org.opencontainers.image.revision': plan['sourceRevision'],
                  'org.opencontainers.image.base.digest': plan['baseDigest'],
                  'org.opencontainers.image.base.name': plan['baseImage'],
                  'io.finite.profile': 'finite', 'io.finite.foundation': 'bluefin',
                  'io.finite.production-eligible': 'false'}
        env = {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REPOSITORY': 'closure-labs/finite',
               'GITHUB_REF': 'refs/heads/experiment', 'SOURCE_DATE_EPOCH': '123'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.bluebuild/containerfile').mkdir(parents=True)
            with patch.dict('os.environ', env, clear=True), patch.object(prepare.subprocess, 'run') as run, patch.object(
                    prepare.subprocess, 'check_output', return_value=json.dumps([{'Config': {'Labels': labels}}])):
                prepare.build(plan, root)
                command = run.call_args_list[0].args[0]
                self.assertIn('BASE_IMAGE=' + plan['baseImage'] + '@' + plan['baseDigest'], command)
                self.assertIn('--load', command)
                self.assertNotIn('--push', command)
                self.assertNotIn('SOURCE_DATE_EPOCH', run.call_args_list[0].kwargs['env'])
                self.assertIn('--network=none', run.call_args_list[1].args[0])
                for key in labels:
                    wrong = dict(labels)
                    wrong[key] = 'wrong'
                    with patch.object(prepare.subprocess, 'check_output', return_value=json.dumps([{'Config': {'Labels': wrong}}])):
                        with self.assertRaisesRegex(ValueError, 'labels do not match'):
                            prepare.build(plan, root)

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


if __name__ == '__main__':
    unittest.main()
