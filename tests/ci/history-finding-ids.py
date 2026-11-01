"""Tiny histories prove that historical ID exceptions cannot hide other findings."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import history_finding_ids as history
import history_snapshot as snapshot


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name);self.repo = self.root / 'repo';self.repo.mkdir()
        self.git('init', '-q', '-b', 'main');self.commit('readme', 'base\n')
        finding = {'profile': 'finite', 'component': 'pkg:rpm/fedora/example', 'advisory': 'CVE-2026-12345',
                   'exposure': ['/usr/bin/example'], 'severity': 'High', 'cvss': 8.0,
                   'knownExploited': False, 'versions': ['1'], 'aliases': ['CVE-2026-12345'], 'fixVersions': []}
        finding['key'] = history.packets.canonical_hash({k: finding[k] for k in ('profile', 'component', 'advisory', 'exposure')})
        self.value = {'schema': 1, 'kind': 'security-findings', 'payload': {
            'profiles': ['finite'], 'findings': [finding], 'disposition': 'accepted', 'supersedes': [],
            'rationale': 'Synthetic identifier fixture.', 'packet': {'reference': 'ghcr.io/closure-labs/finite-decisions@sha256:' + 'a'*64,
            'sha256': 'b'*64, 'producer': {'repository': 'closure-labs/finite', 'workflow': 'build.yml',
            'runId': 7, 'runAttempt': 1, 'headSha': 'c'*40,
            'artifacts': [{'id': 1, 'name': 'security-finite-7-1', 'digest': 'sha256:' + 'd'*64}]}}}}

    def git(self, *args):
        return subprocess.check_output(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null', *args], cwd=self.repo,
            stderr=subprocess.DEVNULL, text=True).strip()

    def commit(self, path, text):
        target = self.repo / path;target.parent.mkdir(parents=True, exist_ok=True);target.write_text(text)
        self.git('add', path);self.git('commit', '-qm', 'synthetic fixture')
        return self.git('rev-parse', 'HEAD')

    def packet(self, value=None, path=None, text=None):
        value = value or self.value
        path = path or history.PREFIX + '/' + history.packets.canonical_hash(value) + '.json'
        self.commit(path, text if text is not None else json.dumps(value, indent=2) + '\n')
        return path

    def ignores(self):
        return history.fingerprints(self.repo, self.git('rev-parse', 'HEAD'))

    def scan(self, ignores):
        binary = shutil.which('gitleaks')
        if not binary:self.skipTest('Cached upstream Gitleaks unavailable')
        self.assertEqual(subprocess.check_output([binary, 'version'], text=True).strip(), '8.30.1')
        config = self.root / 'config';config.write_text('[extend]\nuseDefault = true\n')
        ignore = self.root / 'ignore';ignore.write_text(''.join(x + '\n' for x in ignores))
        result = subprocess.run([binary, 'git', str(self.repo), '--config', str(config),
            '--gitleaks-ignore-path', str(ignore), '--ignore-gitleaks-allow', '--redact=100',
            '--no-banner', '--log-level=error', '--exit-code=2',
            '--log-opts=--all --full-history --diff-merges=first-parent --text --no-ext-diff --no-textconv'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.returncode

    def test_real_engine_exact_main_blob_across_first_parent_merge(self):
        self.git('branch', 'topic');path = self.packet();introduced = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-q', 'topic');self.commit('topic', 'side branch\n')
        self.git('merge', '-q', '--no-ff', '-m', 'inherit', 'main');merged = self.git('rev-parse', 'HEAD')
        self.assertEqual(self.scan([]), 2)
        ignores = self.ignores();self.assertEqual(len(ignores), 2)
        self.assertEqual({x.split(':')[0] for x in ignores}, {introduced, merged})
        self.assertTrue(all(':' + path + ':generic-api-key:' in x for x in ignores))
        self.assertEqual(self.scan(ignores), 0)

    def test_real_engine_preserves_credentials_in_same_packet_and_outside_path(self):
        # Synthetic recognizable token exists only inside this temporary Git graph.
        token = 'ghp_' + '9F0r2JtQ6Lw8aD3sG7hK1mN5pR4vXyZcBeTu'
        self.value['payload']['rationale'] = 'token = "' + token + '"'
        self.packet()
        ignores = self.ignores();self.assertEqual(len(ignores), 1)
        self.assertEqual(self.scan(ignores), 2)

    def test_real_generic_key_outside_verified_path_still_blocks(self):
        self.packet();self.commit('outside.json', json.dumps({'key': self.value['payload']['findings'][0]['key']}))
        ignores = self.ignores();self.assertEqual(len(ignores), 1)
        self.assertEqual(self.scan(ignores), 2)

    def test_forged_duplicate_minified_relocated_and_spoofed_packets_get_no_exception(self):
        for kind in ('forged', 'duplicate', 'minified', 'relocated', 'path'):
            with self.subTest(kind=kind):
                value = copy.deepcopy(self.value);path = None
                if kind == 'forged':value['payload']['findings'][0]['key'] = hashlib.sha256(b'forged').hexdigest()
                if kind == 'relocated':value['payload']['rationale'] = {'key': value['payload']['findings'][0].pop('key')}
                text = json.dumps(value, indent=2) + '\n'
                if kind == 'duplicate':text = text.replace('"schema": 1,', '"schema": 1, "schema": 1,')
                if kind == 'minified':text = json.dumps(value) + '\n'
                if kind == 'path':path = history.PREFIX + '/' + 'e'*64 + '.json'
                self.packet(value, path=path, text=text)
        self.assertEqual(self.ignores(), [])
        self.assertEqual(self.scan([]), 2)

    def test_another_generic_match_on_the_key_line_gets_no_fingerprint(self):
        # Standard fingerprints do not include matched bytes. Therefore even a
        # plausible ID must receive NO exception if another field shares its line.
        value = copy.deepcopy(self.value)
        value['payload']['findings'][0]['token'] = hashlib.sha256(b'synthetic credential').hexdigest()
        rendered = json.dumps(value, indent=2) + '\n'
        key = value['payload']['findings'][0]['key']
        token = value['payload']['findings'][0]['token']
        rendered = rendered.replace('        "key": "' + key + '",\n        "token": "' + token + '"\n',
            '        "key": "' + key + '", "token": "' + token + '"\n')
        self.assertEqual(json.loads(rendered), value)
        self.packet(value, text=rendered)
        self.assertEqual(self.ignores(), [])
        self.assertEqual(self.scan([]), 2)

    def test_other_ref_blob_changed_at_same_path_and_removed_packets_stay_scanned(self):
        path = self.packet();self.git('branch', 'untrusted-side')
        self.git('checkout', '-q', 'untrusted-side')
        forged = copy.deepcopy(self.value);forged['payload']['findings'][0]['key'] = hashlib.sha256(b'forged').hexdigest()
        altered = self.commit(path, json.dumps(forged, indent=2) + '\n')
        self.git('checkout', '-q', 'main')
        ignores = self.ignores();self.assertEqual(len(ignores), 1)
        self.assertFalse(any(x.startswith(altered + ':') for x in ignores))
        self.assertEqual(self.scan(ignores), 2)
        self.git('rm', path);self.git('commit', '-qm', 'remove packet')
        self.assertEqual(self.ignores(), [])

    def test_wrong_anchor_shallow_and_budget_exhaustion_fail_closed(self):
        self.packet()
        with self.assertRaises(ValueError):history.fingerprints(self.repo, 'f'*40)
        with patch.object(history, 'MAX_COMMITS', 0):
            with self.assertRaises(ValueError):self.ignores()
        with patch.object(history, 'MAX_FINGERPRINTS', 0):
            with self.assertRaises(ValueError):self.ignores()
        (self.repo/'.git/shallow').write_text(self.git('rev-parse', 'HEAD') + '\n')
        with self.assertRaises(ValueError):self.ignores()

    def test_failed_cli_clears_stale_output_and_logs_only_fixed_error(self):
        output = self.root / 'exceptions';output.write_text('stale-receipt\n')
        result = subprocess.run([sys.executable, '-I', str(ROOT/'scripts/ci/history_finding_ids.py'),
            '--candidate', str(self.repo), '--anchor', 'f'*40, '--output', str(output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(output.read_text(), '')
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, 'Unable to validate historical packet IDs; no audit receipt granted.\n')

    def test_snapshot_binds_full_refs_source_and_scanner_configuration(self):
        self.packet();source = self.git('rev-parse', 'HEAD')
        config = self.root/'config';config.write_bytes(snapshot.CONFIG)
        ignores = self.root/'ignore';ignores.write_text(''.join(x+'\n' for x in self.ignores()))
        value = snapshot.snapshot(self.repo, source, config, ignores, '7', '1')
        self.assertEqual(value['sourceRevision'], source)
        self.assertEqual(value['scanner']['logOptions'][0], '--all')
        self.assertEqual(value['scanner']['exceptionFingerprintCount'], 1)
        self.assertEqual(value['refs'][0]['name'], 'refs/heads/main')
        snapshot.check(self.repo, value)
        self.git('branch', 'new-ref')
        with self.assertRaises(ValueError):snapshot.check(self.repo, value)
        with patch.object(snapshot, 'MAX_REFS', 0):
            with self.assertRaises(ValueError):snapshot.refs(self.repo)
        config.write_text('[allowlist]\nregexes=[".+"]\n')
        with self.assertRaises(ValueError):snapshot.snapshot(self.repo, source, config, ignores, '7', '1')

    def test_snapshot_cli_checks_manifest_without_printing_ref_or_file_payloads(self):
        config = self.root/'config';config.write_bytes(snapshot.CONFIG)
        ignores = self.root/'ignore';ignores.write_text('')
        manifest = self.root/'manifest';source = self.git('rev-parse', 'HEAD')
        command = [sys.executable, '-I', str(ROOT/'scripts/ci/history_snapshot.py'),
            '--candidate', str(self.repo), '--manifest', str(manifest)]
        env = dict(os.environ, GITHUB_SHA=source, GITHUB_RUN_ID='7', GITHUB_RUN_ATTEMPT='1')
        result = subprocess.run(command+['--config', str(config), '--ignores', str(ignores)], env=env, capture_output=True)
        self.assertEqual(result.returncode, 0);self.assertEqual(result.stdout+result.stderr, b'')
        self.assertEqual(manifest.stat().st_mode & 0o777, 0o600)
        result = subprocess.run(command+['--check'], capture_output=True)
        self.assertEqual(result.returncode, 0);self.assertEqual(result.stdout+result.stderr, b'')
        self.git('branch', 'moved-ref')
        result = subprocess.run(command+['--check'], capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b'')
        self.assertEqual(result.stderr, b'Unable to bind historical scan refs and configuration.\n')

    def test_provenance_categories_observe_but_never_waive_findings(self):
        path = self.packet();commit = self.git('rev-parse', 'HEAD')
        _, lines = history.packets.proposal_lines((self.repo/path).read_bytes(), path)
        finding = {'RuleID': 'generic-api-key', 'Commit': commit, 'File': path, 'StartLine': lines[0]}
        outside = dict(finding, File='outside.json')
        other = dict(finding, RuleID='sourcegraph-access-token')
        self.assertEqual(snapshot.provenance_counts(self.repo, [finding, outside, other]), {
            'canonicalPacketIdWithoutMainException': 1, 'unclassifiedGenericKey': 1, 'otherDefaultRule': 1})
        forged = copy.deepcopy(self.value);forged['payload']['findings'][0]['key'] = hashlib.sha256(b'forged').hexdigest()
        bad = self.packet(forged);commit = self.git('rev-parse', 'HEAD')
        result = snapshot.provenance_counts(self.repo, [dict(finding, Commit=commit, File=bad)])
        self.assertEqual(result['unclassifiedGenericKey'], 1)
        self.assertEqual(result['canonicalPacketIdWithoutMainException'], 0)

    def test_symlinks_do_not_anchor_exceptions(self):
        path = self.packet();target = self.repo/path;raw = target.read_text();target.unlink()
        (self.repo/'packet-data').write_text(raw);target.symlink_to('../../../packet-data')
        self.git('add', path, 'packet-data');self.git('commit', '-qm', 'symlink')
        self.assertEqual(self.ignores(), [])


if __name__ == '__main__':unittest.main()
