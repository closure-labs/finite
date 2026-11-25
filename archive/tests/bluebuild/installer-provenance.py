#!/usr/bin/env python3
"""Observe once, bound evidence, fail before VM work and preserve failures."""
import base64
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('provenance', ROOT / 'scripts/bluebuild/installer-provenance.py')
p = importlib.util.module_from_spec(spec); spec.loader.exec_module(p)


def runtime():
    core = {name: {'count': 2, 'sha256': 'a' * 64} for name in
            ('runtimeRpms', 'installerRpms', 'repositoryMetadata', 'repositoryConfiguration')}
    return {**core, 'schema': 1, 'authorizesPublication': False,
            'cohortSha256': p.digest(core), 'compression': {'type': 'xz', 'args': ['-Xbcj', 'x86']}}


class Provenance(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def capture(self, text, code=0, expected=None):
        target = self.root / 'runtime.json'
        command = [sys.executable, '-c', 'import sys;print(' + repr(text) + ');sys.exit(' + str(code) + ')']
        if expected:
            # Exercise the real capture CLI and environment boundary too.
            import os
            env = dict(os.environ, FINITE_INSTALLER_BENCHMARK=json.dumps({'runtimeCohorts': {'fresh': expected}}), FINITE_BENCHMARK_PHASE='fresh')
        else:
            import os
            env = dict(os.environ); env.pop('FINITE_INSTALLER_BENCHMARK', None)
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/bluebuild/installer-provenance.py'),
            'capture', '--output', str(target), '--', *command], env=env, capture_output=True)
        return result, target

    def marker(self, value=None):
        return p.MARKER + base64.b64encode(json.dumps(value or runtime()).encode()).decode() + ':END'

    def test_capture_streams_and_retains_partial_evidence_and_original_exit_status(self):
        for status in (0, 42):
            result, target = self.capture('driver prefix ' + self.marker() + '\nremaining output', status)
            self.assertEqual(result.returncode, status, result.stderr.decode())
            self.assertEqual(json.loads(target.read_text()), runtime())
            self.assertIn(b'remaining output', result.stdout)
        result, target = self.capture('failed before Lorax', 17)
        self.assertEqual(result.returncode, 17); self.assertFalse(target.exists())

    def test_missing_malformed_duplicate_forged_and_oversized_records_fail_closed(self):
        altered = runtime(); altered['runtimeRpms']['sha256'] = 'b' * 64
        for text in ('no marker', self.marker() + '\n' + self.marker(), p.MARKER + 'invalid:END',
                     self.marker(altered), p.MARKER + 'x' * (p.LIMIT + 1)):
            with self.subTest(text=text[:50]):
                result, _ = self.capture(text)
                self.assertNotEqual(result.returncode, 0)

    def test_runtime_mismatch_and_unknown_repository_stop_before_vm_work(self):
        self.assertNotEqual(self.capture(self.marker(), expected='f' * 64)[0].returncode, 0)
        value = runtime(); value['repositoryMetadata'] = None
        core = {k: value[k] for k in ('runtimeRpms','installerRpms','repositoryMetadata','repositoryConfiguration')}
        value['cohortSha256'] = p.digest(core)
        self.assertNotEqual(self.capture(self.marker(value), expected=value['cohortSha256'])[0].returncode, 0)
        self.assertIsNone(p.validate(value)['repositoryMetadata'])

    def test_inventory_is_order_independent_and_repositories_are_bounded(self):
        self.assertEqual(p.inventory(b'b\na\n'), p.inventory(b'a\nb\n'))
        for data in (b'', b'x' * (2 * 1024 * 1024 + 1)):
            with self.assertRaises(ValueError): p.inventory(data)
        self.assertIsNone(p.file_inventory(self.root, 'repomd.xml'))
        repo = self.root / 'repomd.xml'; repo.write_text('metadata')
        self.assertEqual(p.file_inventory([self.root], 'repomd.xml')['count'], 1)
        repo.unlink(); repo.symlink_to(ROOT / 'flake.lock')
        with self.assertRaises(ValueError): p.file_inventory(self.root, 'repomd.xml')

    def test_smoke_uses_the_existing_help_option_and_checks_real_inventory_paths(self):
        class Builder:
            def create_squashfs_runtime(self, outfile='/tmp/runtime', compression='xz', compressargs=None, size=2):
                pass
        config = SimpleNamespace()
        dnf = ModuleType('libdnf5'); dnf.base = SimpleNamespace(Base=lambda: SimpleNamespace(get_config=lambda: config))
        package = ModuleType('pylorax'); tree = ModuleType('pylorax.treebuilder'); tree.RuntimeBuilder = Builder
        package.treebuilder = tree
        def checked(command, **kwargs):
            # In the real CLI --version takes an argument; --help exits zero.
            self.assertEqual(command, ['/usr/local/bin/lorax', '--help'])
            self.assertEqual(kwargs, {'check': True, 'timeout': 30})
        with patch.dict(sys.modules, {'libdnf5': dnf, 'pylorax': package, 'pylorax.treebuilder': tree}), \
                patch.object(p, 'limited_output', return_value=b'package-0:1-1.x86_64 abcdef\n') as queried, \
                patch.object(p.subprocess, 'run', side_effect=checked) as run, contextlib.redirect_stdout(io.StringIO()):
            p.smoke()
        run.assert_called_once()
        self.assertEqual(queried.call_count, 2)
        self.assertEqual(queried.call_args_list[0].args[0][:3], ['rpm', '--root', '/'])
        self.assertFalse(Path(config.cachedir).exists())

    def test_hook_delegates_exactly_once_preserves_arguments_result_and_restores_methods(self):
        calls = []
        class Builder:
            def install(self, *args, **kwargs): calls.append(('install', args, kwargs)); return 7
            def create_squashfs_runtime(self, outfile='/tmp/runtime', compression='xz', compressargs=None, size=2):
                calls.append(('create', outfile, compression, compressargs, size)); return 9
        original_install, original_create = Builder.install, Builder.create_squashfs_runtime
        package = ModuleType('pylorax'); tree = ModuleType('pylorax.treebuilder'); tree.RuntimeBuilder = Builder
        package.treebuilder = tree
        core = {k: runtime()[k] for k in ('runtimeRpms','installerRpms','repositoryMetadata','repositoryConfiguration')}
        def run(path, run_name):
            builder = Builder(); self.assertEqual(builder.install('same', flag=True), 7)
            self.assertEqual(builder.create_squashfs_runtime('/out', 'zstd', ['-Xcompression-level', '15'], size=3), 9)
        output = io.StringIO()
        with patch.dict(sys.modules, {'pylorax': package, 'pylorax.treebuilder': tree}), \
                patch.object(p.runpy, 'run_path', side_effect=run), patch.object(p, 'observe_runtime', return_value=core), \
                contextlib.redirect_stdout(output):
            p.hook()
        self.assertEqual(calls, [('install', ('same',), {'flag': True}), ('create', '/out', 'zstd', ['-Xcompression-level', '15'], 3)])
        self.assertIs(Builder.install, original_install); self.assertIs(Builder.create_squashfs_runtime, original_create)
        value = json.loads(base64.b64decode(output.getvalue().split(p.MARKER)[1].split(':END')[0]))
        self.assertEqual(value['compression'], {'type': 'zstd', 'args': ['-Xcompression-level', '15']})


if __name__ == '__main__':
    unittest.main()
