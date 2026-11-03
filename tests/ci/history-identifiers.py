"""Real upstream scanner and isolated Git fixtures for exact historical exceptions."""
import copy
import hashlib
import importlib.util
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
sys.path.insert(0, str(ROOT/'scripts/ci'))
import history_identifiers as identifiers
import history_frozen_refs as frozen
import history_snapshot as snapshot


class PolicyData(unittest.TestCase):
    def test_reviewed_inventory_and_frozen_binding(self):
        policy, value = identifiers.load_policy()
        baseline = frozen.load_baseline()
        self.assertEqual(len(policy), 719)
        self.assertEqual(value['baseline']['manifestDigest'], frozen.BASELINE_DIGEST)
        self.assertEqual(value['baseline']['source'], baseline['sourceRevision'])
        self.assertEqual(len(baseline['refs']), 393)
        self.assertEqual(sum(fp.split(':')[-2]=='sourcegraph-access-token' for fp in policy), 2)

    def test_mismatched_policy_bytes_fail_closed(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            for path in identifiers.DIRECTORY.glob('history-identifiers.*'):
                shutil.copyfile(path, directory/path.name)
            path = directory/'history-identifiers.gitleaksignore';path.write_text(path.read_text()+'forged\n')
            with self.assertRaises(identifiers.Invalid):identifiers.load_policy(directory)

    def test_frozen_input_digest_mismatch_is_not_replaced_by_current_refs(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name)/'baseline';path.write_text('{}')
            with patch.object(frozen, 'BASELINE', path), self.assertRaises(ValueError):frozen.load_baseline()

    @unittest.skipUnless(shutil.which('gitleaks'), 'Cached upstream engine unavailable')
    def test_policy_metadata_itself_passes_default_rules(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name);(p/'config').write_bytes(snapshot.CONFIG);(p/'ignore').write_text('')
            result=subprocess.run([shutil.which('gitleaks'),'dir',str(identifiers.DIRECTORY),
                '--config',str(p/'config'),'--gitleaks-ignore-path',str(p/'ignore'),'--ignore-gitleaks-allow',
                '--redact=100','--no-banner','--log-level=error'],capture_output=True)
            self.assertEqual(result.returncode,0)


@unittest.skipUnless(shutil.which('gitleaks'), 'Cached upstream engine unavailable')
class RealScanner(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.repo=self.root/'repo';self.repo.mkdir()
        self.git('init','-q','-b','main')
        self.config=self.root/'config';self.config.write_bytes(snapshot.CONFIG)
        self.ignore=self.root/'ignore';self.report=self.root/'report';self.report.touch(mode=0o600)
        self.binary=shutil.which('gitleaks')
        self.assertEqual(subprocess.check_output([self.binary,'version'],text=True).strip(),'8.30.1')
        self.public=hashlib.sha256(b'synthetic public identifier').hexdigest()
        self.commit('proof.json',json.dumps({'keyFingerprint':self.public},indent=2)+'\n')

    def git(self,*args):
        return subprocess.check_output(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
            '-c','commit.gpgsign=false','-c','core.hooksPath=/dev/null','-C',str(self.repo),*args],text=True,stderr=subprocess.DEVNULL).strip()

    def commit(self,path,text):
        p=self.repo/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
        self.git('add',path);self.git('commit','-qm','synthetic fixture');return self.git('rev-parse','HEAD')

    def scan(self,ignores=()):
        self.ignore.write_text(''.join(fp+'\n' for fp in ignores))
        result=subprocess.run([self.binary,'git',str(self.repo),'--config',str(self.config),
            '--gitleaks-ignore-path',str(self.ignore),'--ignore-gitleaks-allow','--redact=100','--no-banner',
            '--log-level=error','--exit-code=2','--report-format=json','--report-path',str(self.report),
            '--log-opts=--all --full-history --diff-merges=first-parent --text --no-ext-diff --no-textconv'],capture_output=True)
        self.assertIn(result.returncode,(0,2))
        return result.returncode,json.loads(self.report.read_text())

    def policy(self,finding,identifier=None,shape='standalone-json-public-identifier',kind='public-key-Git-blob'):
        raw=subprocess.check_output(['git','-C',str(self.repo),'show',finding['Commit']+':'+finding['File']],stderr=subprocess.DEVNULL)
        line=raw.decode().splitlines()[finding['StartLine']-1]
        oid=self.git('rev-parse',finding['Commit']+':'+finding['File'])
        return {finding['Fingerprint']:{'blobGitSha1':oid,'blobSha256':identifiers.digest(raw),
            'lineSha256':identifiers.digest(line.encode()),'identifierSha256':identifiers.digest((identifier or self.public).encode()),
            'shape':shape,'binding':{'kind':kind}}}

    def test_native_and_allowlist_accepts_only_verified_complete_line(self):
        _, found = self.scan()
        policy = self.policy(found[0])
        config, counts = identifiers.native_config(self.repo, policy, require_complete=True)
        self.config.write_bytes(config)
        self.assertEqual(counts['verifiedExactIdentifierCount'], 1)
        self.assertEqual(self.scan(), (0, []))
        self.assertTrue(config.startswith(b'[extend]\nuseDefault = true\n'))
        self.assertIn(b'condition = "AND"', config)
        self.assertIn(b'regexTarget = "line"', config)

    def test_native_manifest_binds_actual_config_without_public_identifier_payload(self):
        _, found = self.scan()
        policy = self.policy(found[0])
        with patch.object(identifiers, 'load_policy', return_value=(policy, {'version': 'fixture'})):
            value = snapshot.snapshot(self.repo, self.git('rev-parse','HEAD'), self.config,
                self.ignore, '1', '1', native_identifiers=True, require_complete=True)
        self.assertEqual(value['schema'], 2)
        scanner = value['scanner']
        self.assertEqual(scanner['configSha256'], hashlib.sha256(self.config.read_bytes()).hexdigest())
        self.assertTrue(scanner['defaultRules'])
        self.assertFalse(scanner['inlineAllows'])
        self.assertIsNone(scanner['config'])
        self.assertEqual(scanner['nativeIdentifierPolicy']['verifiedExactIdentifierCount'], 1)
        self.assertNotIn(self.public, json.dumps(value))
        snapshot.check(self.repo, value)
        self.commit('unrelated.txt','changed refs\n')
        with self.assertRaises(ValueError): snapshot.check(self.repo, value)

    def test_native_same_public_line_at_a_new_commit_is_a_finding(self):
        _, found = self.scan()
        config, _ = identifiers.native_config(self.repo, self.policy(found[0]))
        raw = (self.repo/'proof.json').read_text()
        self.commit('proof.json', '{}\n')
        revision = self.commit('proof.json', raw)
        self.config.write_bytes(config)
        status, remaining = self.scan()
        self.assertEqual(status, 2)
        self.assertTrue(any(row['Commit'] == revision for row in remaining))

    def test_native_added_generic_and_provider_credentials_are_not_masked(self):
        _, found = self.scan()
        policy = self.policy(found[0])
        config, _ = identifiers.native_config(self.repo, policy)
        unknown = hashlib.sha256(b'synthetic unknown credential').hexdigest()
        provider = 'ghp_'+'9F0r2JtQ6Lw8aD3sG7hK1mN5pR4vXyZcBeTu'
        for name, text in (
                ('same-line.json', '{"keyFingerprint": "'+self.public+'", "api_key": "'+unknown+'"}\n'),
                ('provider.txt', 'token = "'+provider+'"\n'),
                ('other-path.json', '{"keyFingerprint": "'+self.public+'"}\n'),
                ('other-field.json', '{"api_key": "'+self.public+'"}\n')):
            self.commit(name, text)
        self.config.write_bytes(config)
        status, remaining = self.scan()
        self.assertEqual(status, 2)
        self.assertEqual({row['File'] for row in remaining},
                         {'same-line.json', 'provider.txt', 'other-path.json', 'other-field.json'})
        self.assertTrue(any(row['RuleID'] == 'github-pat' for row in remaining))

    def test_native_source_proofs_fail_before_any_config_is_returned(self):
        _, found = self.scan()
        policy = self.policy(found[0])
        for field in ('blobGitSha1', 'blobSha256', 'lineSha256', 'identifierSha256'):
            forged = copy.deepcopy(policy)
            forged[found[0]['Fingerprint']][field] = 'f'*(40 if field == 'blobGitSha1' else 64)
            with self.subTest(field=field), self.assertRaises(identifiers.Invalid):
                identifiers.native_config(self.repo, forged)

    def test_native_history_limit_is_not_a_partial_allowance(self):
        _, found = self.scan()
        with patch.object(identifiers.history_finding_ids, 'MAX_COMMITS', 0):
            with self.assertRaises(identifiers.Invalid) as context:
                identifiers.native_config(self.repo, self.policy(found[0]))
        self.assertEqual(context.exception.reason, 'history-limit')

    def test_native_missing_catalog_commit_is_not_substituted(self):
        _, found = self.scan()
        policy = self.policy(found[0])
        fingerprint, item = next(iter(policy.items()))
        missing = {'1'*40+fingerprint[40:]: item}
        config, counts = identifiers.native_config(self.repo, missing)
        self.assertEqual(counts['verifiedExactIdentifierCount'], 0)
        self.assertEqual(counts['unreachableCatalogEntryCount'], 1)
        self.assertNotIn(b'allowlists', config)
        with self.assertRaises(identifiers.Invalid):
            identifiers.native_config(self.repo, missing, require_complete=True)

    def test_ambiguous_same_fingerprint_fails_before_any_ignore(self):
        extra=hashlib.sha256(b'second synthetic credential').hexdigest()
        self.commit('shared.json','{\n  "key": "'+self.public+'", "api_key": "'+extra+'"\n}\n')
        _,found=self.scan();shared=[f for f in found if f['File']=='shared.json']
        self.assertEqual(len(shared),2);self.assertEqual(shared[0]['Fingerprint'],shared[1]['Fingerprint'])
        policy=self.policy(shared[0])
        with self.assertRaises(identifiers.Invalid):identifiers.native_config(self.repo,policy)
        self.assertEqual(self.scan(())[0],2)

    def test_other_provider_rule_sharing_a_line_is_never_waived(self):
        token='ghp_'+'9F0r2JtQ6Lw8aD3sG7hK1mN5pR4vXyZcBeTu'
        self.commit('provider.json','{\n  "key": "'+self.public+'", "token": "'+token+'"\n}\n')
        _,found=self.scan();public=[f for f in found if f['File']=='provider.json' and f['RuleID']=='generic-api-key']
        self.assertTrue(public);self.assertTrue(any(f['RuleID']=='github-pat' for f in found))
        policy=self.policy(public[0])
        with self.assertRaises(identifiers.Invalid):identifiers.native_config(self.repo,policy)
        _,remaining=self.scan([public[0]['Fingerprint']])
        self.assertTrue(any(f['RuleID']=='github-pat' for f in remaining))

    def test_python_constant_and_provider_public_git_revision_spans(self):
        self.commit('constant.py',"KEY_SHA256 = '"+self.public+"'\n")
        revision=self.git('rev-parse','HEAD')
        self.commit('revision.json',json.dumps({'sourceRevision':revision,'description':'sourcegraph public revision fixture'},indent=2)+'\n')
        _,found=self.scan()
        constant=next(f for f in found if f['File']=='constant.py')
        git_reference=next(f for f in found if f['File']=='revision.json' and f['RuleID']=='sourcegraph-access-token')
        policy=self.policy(constant,shape='standalone-python-public-key-constant')
        policy.update(self.policy(git_reference,identifier=revision,kind='public-Git-commit-object'))
        policy.update(self.policy(next(f for f in found if f['File']=='proof.json')))
        config, counts = identifiers.native_config(self.repo, policy)
        self.config.write_bytes(config)
        self.assertEqual(counts['verifiedExactIdentifierCount'],3)
        self.assertEqual(self.scan(),(0,[]))

    def test_canonical_packet_identity_uses_full_shared_validator(self):
        spec=importlib.util.spec_from_file_location('history_fixture',ROOT/'tests/ci/history-finding-ids.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        fixture=module.HistoryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        value=copy.deepcopy(fixture.value);identifier=value['payload']['findings'][0]['key']
        path='automation/decisions/security/'+identifiers.packets.canonical_hash(value)+'.json'
        self.commit(path,json.dumps(value,indent=2)+'\n');_,found=self.scan()
        row=next(f for f in found if f['File']==path)
        policy=self.policy(row,identifier=identifier,shape='standalone-recomputed-packet-key',kind='canonical-packet-finding-identity')
        item=policy[row['Fingerprint']];item['binding'].update(packetPath=path,packetBlob=item['blobGitSha1'],packetDigest=item['blobSha256'])
        config, counts = identifiers.native_config(self.repo,policy)
        self.assertEqual(counts['verifiedExactIdentifierCount'],1)
        self.config.write_bytes(config)
        self.assertFalse(any(f['File']==path for f in self.scan()[1]))
        item['binding']['packetDigest']='f'*64
        with self.assertRaises(identifiers.Invalid):identifiers.native_config(self.repo,policy)


class FrozenRefs(unittest.TestCase):
    def test_exact_local_ref_materialization_has_no_checkout_or_extra_history(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);remote=root/'remote';remote.mkdir()
            def git(*args):return subprocess.check_output(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','-c','commit.gpgsign=false','-c','core.hooksPath=/dev/null','-C',str(remote),*args],text=True,stderr=subprocess.DEVNULL).strip()
            git('init','-q','-b','main');(remote/'never-execute.py').write_text('raise RuntimeError("must remain data")\n');git('add','.');git('commit','-qm','fixture')
            revision=git('rev-parse','HEAD');git('tag','-a','-m','annotated public tag','fixture-tag')
            baseline={'sourceRevision':revision,'refs':snapshot.refs(remote)}
            candidate=root/'subject'
            with patch.object(frozen,'REPOSITORY',remote.as_uri()):frozen.prepare(candidate,baseline)
            self.assertEqual(snapshot.refs(candidate),baseline['refs'])
            self.assertEqual(subprocess.check_output(['git','-C',str(candidate),'rev-parse','HEAD'],text=True).strip(),revision)
            self.assertFalse((candidate/'never-execute.py').exists())
            with self.assertRaises(ValueError):frozen.prepare(candidate,baseline)
            incomplete=copy.deepcopy(baseline);incomplete['refs'][0]['object']='1'*40
            with patch.object(frozen,'REPOSITORY',remote.as_uri()),self.assertRaises(subprocess.CalledProcessError):frozen.prepare(root/'missing',incomplete)
            ignores=root/'ignore';ignores.write_text('')
            baseline['scanner']={'exceptionSha256':hashlib.sha256(b'').hexdigest()}
            with patch.object(frozen,'load_baseline',return_value=baseline):
                frozen.check_inputs(candidate,ignores)
                ignores.write_text('changed\n')
                with self.assertRaises(ValueError):frozen.check_inputs(candidate,ignores)


if __name__=='__main__':unittest.main()
