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

    def test_ambiguous_cli_clears_stale_exceptions_and_emits_fixed_error(self):
        policy,_=identifiers.load_policy();fp=next(iter(policy));commit,path,rule,line=fp.rsplit(':',3)
        row={'Commit':commit,'File':path,'RuleID':rule,'StartLine':int(line),'Fingerprint':fp}
        with tempfile.TemporaryDirectory() as name:
            p=Path(name);report=p/'report';report.write_text(json.dumps([row,row]));base=p/'base';base.write_text('')
            output=p/'output';output.write_text('stale exceptions\n');receipt=p/'receipt'
            result=subprocess.run([sys.executable,'-I',str(ROOT/'scripts/ci/history_identifiers.py'),
                '--candidate',name,'--report',str(report),'--status','2','--base-ignores',str(base),
                '--output',str(output),'--receipt',str(receipt)],capture_output=True,text=True)
            self.assertEqual(result.returncode,1);self.assertEqual(output.read_text(),'')
            self.assertEqual(output.stat().st_mode & 0o777,0o600);self.assertEqual(result.stdout,'')
            self.assertEqual(result.stderr,'Unable to verify historical identifier exceptions: ambiguous-fingerprint.\n')
            self.assertEqual(json.loads(receipt.read_text())['reason'],'ambiguous-fingerprint')

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

    def test_known_public_identifier_passes_and_native_engine_decides_final_result(self):
        status,found=self.scan();self.assertEqual(status,2);self.assertEqual(len(found),1)
        policy=self.policy(found[0]);verified=identifiers.verified(self.repo,found,policy,require_complete=True)
        self.assertEqual(verified,[found[0]['Fingerprint']])
        self.assertEqual(self.scan(verified),(0,[]))

    def test_unknown_credential_and_copied_identifier_remain_native_findings(self):
        _,found=self.scan();policy=self.policy(found[0]);original=found[0]['Fingerprint']
        token='ghp_'+'9F0r2JtQ6Lw8aD3sG7hK1mN5pR4vXyZcBeTu'
        self.commit('copied.json',json.dumps({'keyFingerprint':self.public},indent=2)+'\n')
        self.commit('credential.txt','token = "'+token+'"\n')
        _,found=self.scan();verified=identifiers.verified(self.repo,found,policy)
        self.assertEqual(verified,[original]);status,remaining=self.scan(verified);self.assertEqual(status,2)
        self.assertTrue(any(f['File']=='copied.json' for f in remaining))
        self.assertTrue(any(f['RuleID']=='github-pat' for f in remaining))

    def test_changed_commit_same_path_line_is_outside_policy(self):
        _,found=self.scan();policy=self.policy(found[0]);original=found[0]['Fingerprint']
        next_id=hashlib.sha256(b'distinct synthetic credential').hexdigest()
        revision=self.commit('proof.json',json.dumps({'keyFingerprint':next_id},indent=2)+'\n')
        _,found=self.scan();verified=identifiers.verified(self.repo,found,policy)
        self.assertEqual(verified,[original])
        _,remaining=self.scan(verified)
        self.assertTrue(any(f['Commit']==revision and f['StartLine']==2 for f in remaining))

    def test_ambiguous_same_fingerprint_fails_before_any_ignore(self):
        extra=hashlib.sha256(b'second synthetic credential').hexdigest()
        self.commit('shared.json','{\n  "key": "'+self.public+'", "api_key": "'+extra+'"\n}\n')
        _,found=self.scan();shared=[f for f in found if f['File']=='shared.json']
        self.assertEqual(len(shared),2);self.assertEqual(shared[0]['Fingerprint'],shared[1]['Fingerprint'])
        policy=self.policy(shared[0])
        with self.assertRaises(identifiers.Invalid) as context:identifiers.verified(self.repo,found,policy)
        self.assertEqual(context.exception.reason,'ambiguous-fingerprint')
        self.assertEqual(self.scan(())[0],2)

    def test_duplicated_row_multiline_span_and_redacted_value_forgery_fail(self):
        _,found=self.scan();policy=self.policy(found[0])
        for rows in ([found[0],copy.deepcopy(found[0])], [dict(found[0],EndLine=found[0]['EndLine']+1)],
                     [dict(found[0],StartColumn=1)], [dict(found[0],Match='REDACTED')],
                     [dict(found[0],Secret='not-redacted')]):
            with self.subTest(case=len(rows)),self.assertRaises(identifiers.Invalid):identifiers.verified(self.repo,rows,policy)

    def test_wrong_blob_line_or_identifier_digest_fail(self):
        _,found=self.scan();policy=self.policy(found[0]);fp=found[0]['Fingerprint']
        for field in ('blobGitSha1','blobSha256','lineSha256','identifierSha256'):
            forged=copy.deepcopy(policy);forged[fp][field]='f'*(40 if field=='blobGitSha1' else 64)
            with self.subTest(field=field),self.assertRaises(identifiers.Invalid):identifiers.verified(self.repo,found,forged)
        with self.assertRaises(identifiers.Invalid):identifiers.verified(self.repo,[],policy,require_complete=True)

    def test_other_provider_rule_sharing_a_line_is_never_waived(self):
        token='ghp_'+'9F0r2JtQ6Lw8aD3sG7hK1mN5pR4vXyZcBeTu'
        self.commit('provider.json','{\n  "key": "'+self.public+'", "token": "'+token+'"\n}\n')
        _,found=self.scan();public=[f for f in found if f['File']=='provider.json' and f['RuleID']=='generic-api-key']
        self.assertTrue(public);self.assertTrue(any(f['RuleID']=='github-pat' for f in found))
        policy=self.policy(public[0])
        with self.assertRaises(identifiers.Invalid):identifiers.verified(self.repo,found,policy)
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
        self.assertEqual(set(identifiers.verified(self.repo,found,policy)),set(policy))

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
        self.assertEqual(identifiers.verified(self.repo,[row],policy),[row['Fingerprint']])
        item['binding']['packetDigest']='f'*64
        with self.assertRaises(identifiers.Invalid):identifiers.verified(self.repo,[row],policy)


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
