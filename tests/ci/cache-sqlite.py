#!/usr/bin/env python3
"""Use real SQLite locks to verify the cache action's unchanged batch SQL."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('cache_sqlite', ROOT / 'scripts/ci/cache-sqlite.py')
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)
CLI = os.environ.get('FINITE_TEST_SQLITE3') or shutil.which('sqlite3')


class Configuration(unittest.TestCase):
    def test_preserves_existing_config_and_is_idempotent_at_both_startup_locations(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / '.sqliterc').write_text('.headers off\n')
            paths = helper.configure(home, timeout_ms=500)
            self.assertEqual(paths, (home / '.sqliterc', home / '.config/sqlite3/sqliterc'))
            helper.configure(home, timeout_ms=700)
            self.assertTrue(paths[0].read_text().startswith('.headers off\n'))
            for path in paths:
                self.assertEqual(path.read_text().count(helper.MARKER), 1)
                self.assertIn('.timeout 700\n', path.read_text())
                self.assertNotIn('.timeout 500', path.read_text())

    def test_rejects_symlinks_and_invalid_timeouts_without_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            for value in (0, -1, 30001, True, '500'):
                with self.subTest(timeout=value), self.assertRaises(ValueError):
                    helper.configure(home, timeout_ms=value)
            self.assertFalse((home / '.sqliterc').exists())
            (home / '.sqliterc').symlink_to(home / 'outside')
            with self.assertRaises(ValueError): helper.configure(home)
            self.assertFalse((home / 'outside').exists())
            (home / '.sqliterc').unlink()
            (home / '.config').symlink_to(home / 'outside')
            with self.assertRaises(ValueError): helper.configure(home)
            self.assertFalse((home / '.sqliterc').exists())

    def test_cli_refuses_local_home_mutation(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(helper, 'configure') as configure, \
                self.assertRaisesRegex(ValueError, 'ephemeral Linux'):
            helper.main()
        configure.assert_not_called()

    def test_verify_prints_only_numeric_timeout_and_fails_on_unloaded_configuration(self):
        for output, accepted in [('15000\n', True), ('0\n', False), ('secret-config-output\n15000\n', False)]:
            with patch.object(helper.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, '')), \
                    contextlib.redirect_stdout(io.StringIO()) as stdout:
                if accepted:
                    helper.verify()
                    self.assertEqual(stdout.getvalue(), 'SQLite CLI cache lock timeout verified: 15000 ms\n')
                else:
                    with self.assertRaises(ValueError): helper.verify()
                    self.assertEqual(stdout.getvalue(), '')

    def test_restore_precedes_resolver_realization_and_secret_mapping(self):
        steps = yaml.safe_load((ROOT / '.github/actions/setup-nix/action.yml').read_text())['runs']['steps']
        def index(name):
            return next(i for i, step in enumerate(steps) if step['name'] == name)
        validate = index('Validate public CI options before cache selection')
        timeout = index('Bound SQLite CLI waits for cache restore and post-job save')
        store = index('Restore Nix checks snapshot')
        sources = index('Restore Nix source downloads only')
        resolver = index('Prepare pinned scoped SecretSpec resolver')
        canonical = index('Resolve declared CI options with SecretSpec')
        mapper = index('Map declared GitHub Actions secrets')
        self.assertLess(validate, timeout)
        self.assertLess(timeout, store)
        self.assertLess(timeout, sources)
        self.assertLess(max(store, sources), resolver)
        self.assertLess(resolver, canonical)
        self.assertLess(canonical, mapper)
        self.assertEqual(steps[validate]['run'], 'python3 scripts/ci/ci-options.py --github-env')
        self.assertEqual(steps[timeout]['if'], steps[store]['if'])
        # No build/realization before restoration: source cache can now help the
        # resolver, and no recent resolver daemon write races the checkpoint.
        self.assertFalse(any('nix build' in step.get('run', '') for step in steps[:store]))

    def test_measured_cache_defaults_and_explicit_experiments(self):
        steps = yaml.safe_load((ROOT / '.github/actions/setup-nix/action.yml').read_text())['runs']['steps']
        conditions = {step['name']: step['if'] for step in steps if 'if' in step}
        def selected(name, mode, profile, job, enabled):
            expression = conditions[name].replace('inputs.cache-mode', 'inputs.cache_mode')
            expression = expression.replace('inputs.cache-profile', 'inputs.cache_profile')
            expression = expression.replace('&&', ' and ').replace('||', ' or ').replace('!(', 'not (')
            return bool(eval(expression, {'__builtins__': {}}, {
                'inputs': SimpleNamespace(cache_mode=mode, cache_profile=profile),
                'github': SimpleNamespace(job=job),
                'env': SimpleNamespace(FINITE_OPTIMIZED_CACHES=enabled)}))
        # Defaults preserve checks and avoid unnecessary restore work in small
        # jobs; explicit modes remain useful for controlled measurements/rollback.
        cases = [
            ('', 'auto', 'checks', 'true', True, False),
            ('', 'checks', 'audit', 'true', True, False),
            ('', 'auto', 'audit', 'true', False, False),
            ('', 'sources', 'build', 'true', False, False),
            ('', 'auto', 'audit', 'false', True, False),
            ('baseline', 'sources', 'audit', 'true', True, False),
            ('optimized', 'sources', 'audit', 'true', False, True),
            ('optimized', 'sources', 'audit', 'false', False, True),
            ('optimized', 'checks', 'audit', 'true', True, False),
            ('optimized', 'auto', 'checks', 'true', True, False),
            ('none', 'checks', 'checks', 'false', False, False),
            ('none', 'sources', 'audit', 'true', False, False),
        ]
        for mode, profile, job, enabled, store, sources in cases:
            with self.subTest(mode=mode, profile=profile, job=job, enabled=enabled):
                self.assertEqual(selected('Restore Nix checks snapshot', mode, profile, job, enabled), store)
                self.assertEqual(selected('Restore Nix source downloads only', mode, profile, job, enabled), sources)
                self.assertEqual(selected('Bound SQLite CLI waits for cache restore and post-job save',
                                          mode, profile, job, enabled), store)


@unittest.skipUnless(CLI, 'The Nix contract check supplies sqlite3')
class Locks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.rc, _ = helper.configure(self.root, timeout_ms=300)
        self.database = self.root / 'fixture.sqlite'

    def cli(self, sql='PRAGMA wal_checkpoint(TRUNCATE);', *, automatic=False, env=None):
        # Explicit -init avoids touching/reading the actual local passwd home;
        # otherwise this is the exact upstream command/database/SQL shape.
        arguments = [CLI] if automatic else [CLI, '-init', str(self.rc)]
        return subprocess.run([*arguments, str(self.database), sql], capture_output=True,
                              text=True, env=env, timeout=5)

    def lock(self, mode='DELETE'):
        connection = sqlite3.connect(self.database, check_same_thread=False)
        connection.execute('PRAGMA journal_mode=' + mode)
        connection.execute('CREATE TABLE fixture(value)')
        connection.commit()
        connection.execute('BEGIN EXCLUSIVE' if mode == 'DELETE' else 'BEGIN IMMEDIATE')
        connection.execute('INSERT INTO fixture VALUES(1)')
        return connection

    def test_batch_config_applies_before_sql_and_recovers_a_transient_schema_lock(self):
        result = self.cli('PRAGMA busy_timeout;')
        self.assertEqual((result.returncode, result.stdout.strip()), (0, '300'))
        helper.configure(self.root, timeout_ms=2000)
        connection = self.lock()
        def unlock():
            time.sleep(0.2)
            connection.commit()
        thread = threading.Thread(target=unlock)
        thread.start()
        try:
            result = self.cli()
        finally:
            thread.join(timeout=3)
            connection.close()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip().split('|')[0], '0')
        self.assertFalse(thread.is_alive())

    def test_permanent_schema_lock_remains_a_bounded_failure(self):
        connection = self.lock()
        started = time.monotonic()
        try:
            result = self.cli()
        finally:
            connection.rollback()
            connection.close()
        elapsed = time.monotonic() - started
        # CLI releases differ in whether SQLite error 5 becomes exit 5 or the
        # generic exit 1. The cache contract requires a bounded failure.
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('database is locked', result.stderr)
        self.assertGreaterEqual(elapsed, 0.2)
        self.assertLess(elapsed, 3)

    def test_invalid_sql_still_fails_and_wal_busy_rows_are_not_reinterpreted(self):
        result = self.cli('this is invalid SQL;')
        self.assertNotEqual(result.returncode, 0)
        connection = self.lock('WAL')
        started = time.monotonic()
        try:
            result = self.cli()
        finally:
            connection.rollback()
            connection.close()
        # Upstream's PRAGMA returns a busy row, not a command error, for a
        # persistent WAL writer. The timeout fix does not mask or reinterpret it.
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip().split('|')[0], '1')
        self.assertLess(time.monotonic() - started, 3)

    def test_newer_sqlite_automatically_reads_isolated_xdg_config_in_batch_mode(self):
        version = subprocess.check_output([CLI, '--version'], text=True, timeout=5).split()[0]
        if tuple(map(int, version.split('.')[:2])) < (3, 51):
            self.skipTest('SQLite before XDG config support is covered by explicit-init tests')
        env = {**os.environ, 'XDG_CONFIG_HOME': str(self.root / '.config')}
        with contextlib.redirect_stdout(io.StringIO()) as output:
            helper.verify(CLI, timeout_ms=300, env=env)
        self.assertEqual(output.getvalue(), 'SQLite CLI cache lock timeout verified: 300 ms\n')


if __name__ == '__main__':
    unittest.main()
