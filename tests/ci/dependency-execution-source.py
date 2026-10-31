"""Real Git merges cannot smuggle base-only execution through dependency admission."""
import base64
from copy import deepcopy
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import re
import unittest

SOURCE=Path(__file__).resolve().parents[2]
sys.dont_write_bytecode=True
sys.path.insert(0,str(SOURCE/'scripts/ci'))
import dependency_update as dep
spec=importlib.util.spec_from_file_location('admission_proof',SOURCE/'scripts/ci/ci-run-admission.py')
adm=importlib.util.module_from_spec(spec); spec.loader.exec_module(adm)
NEW='e'*40
WORKFLOW='.github/workflows/codeql.yml'
ACTION='.github/actions/setup-nix/action.yml'
EXTRA_JOB='''  base-only-writer:
    runs-on: ubuntu-24.04
    permissions:
      contents: write
      id-token: write
    env:
      CANDIDATE_SECRET: ${{ secrets.FIXTURE_ONLY_SECRET }}
    steps:
      - run: echo fixture-only-never-executed
'''

class Native:
    def __init__(self, case):
        self.directory=tempfile.TemporaryDirectory(prefix='finite-source-graph-')
        self.root=Path(self.directory.name); self.reads=[]; self.posts=[]
        self.git('init','-q'); self.git('config','user.name','Offline fixture'); self.git('config','user.email','fixture@example.invalid')
        self.git('config','commit.gpgsign','false')
        self.write(WORKFLOW,BEFORE); self.write(ACTION,COMPOSITE)
        self.git('add','.'); self.git('commit','-qm','Common base'); self.common=self.git('rev-parse','HEAD')
        self.write(WORKFLOW,AFTER); self.git('add','.'); self.git('commit','-qm','Official bot pin update'); self.head=self.git('rev-parse','HEAD')
        self.git('checkout','-q','--detach',self.common)
        if case=='main-only-workflow-job': self.write(WORKFLOW,BEFORE+EXTRA_JOB)
        elif case=='main-only-composite-code': self.write(ACTION,COMPOSITE+'    - shell: bash\n      run: echo base-only-code-never-executed\n')
        else: self.write('README.md','Harmless current-main documentation\n')
        self.git('add','.'); self.git('commit','-qm','Diverged live main executable change'); self.base=self.git('rev-parse','HEAD')
        merge_tree=self.git('merge-tree','--write-tree',self.base,self.head)
        self.merge=self.git('commit-tree',merge_tree,'-p',self.base,'-p',self.head,input='Synthetic PR merge\n')
        self.repo={'id':dep.REPOSITORY_ID,'full_name':dep.REPOSITORY}
        self.pull={'number':7,'state':'open','draft':False,'user':deepcopy(dep.BOT),'changed_files':1,
                   'base':{'sha':self.base,'ref':'main','repo':deepcopy(self.repo)},
                   'head':{'sha':self.head,'ref':'dependabot/actions','repo':deepcopy(self.repo)},
                   'merge_commit_sha':self.merge,'mergeable':True}
        self.run={'id':40,'run_attempt':1,'workflow_id':50,'path':WORKFLOW,'event':'pull_request',
                  'head_sha':self.head,'head_branch':'dependabot/actions','repository':deepcopy(self.repo),
                  'head_repository':deepcopy(self.repo),'status':'completed','conclusion':'action_required',
                  'pull_requests':[{'number':7,'base':{'sha':self.base},'head':{'sha':self.head}}]}
    def git(self,*args,input=None):
        return subprocess.check_output(['git',*args],cwd=self.root,input=input,text=True,stderr=subprocess.DEVNULL).strip()
    def write(self,path,text):
        p=self.root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    def __call__(self,endpoint):
        self.reads.append(endpoint);prefix='repos/'+dep.REPOSITORY
        if endpoint==prefix+'/git/ref/heads/main': return {'ref':'refs/heads/main','object':{'type':'commit','sha':self.base}}
        if endpoint==prefix+'/pulls/7':return deepcopy(self.pull)
        if '/pulls/7/files?' in endpoint:return [{'filename':WORKFLOW,'status':'modified'}]
        if endpoint==prefix+f'/compare/{self.base}...{self.head}':
            return {'base_commit':{'sha':self.base},'merge_base_commit':{'sha':self.git('merge-base',self.base,self.head)}}
        if '/git/trees/' in endpoint:
            sha=endpoint.split('/git/trees/')[1].split('?')[0]
            entries=[]
            for line in self.git('ls-tree','-r',sha).splitlines():
                left,path=line.split('\t');mode,kind,oid=left.split()
                entries.append({'path':path,'mode':mode,'type':kind,'sha':oid})
            return {'truncated':False,'tree':entries}
        if '/git/blobs/' in endpoint:
            sha=endpoint.rsplit('/',1)[1]
            raw=subprocess.check_output(['git','cat-file','blob',sha],cwd=self.root)
            return {'sha':sha,'size':len(raw),'encoding':'base64','content':base64.b64encode(raw).decode()}
        if endpoint=='repos/actions/checkout/git/ref/tags/v99.0.1':return {'ref':'refs/tags/v99.0.1','object':{'type':'commit','sha':NEW}}
        if endpoint.endswith('/actions/runs/40'):return deepcopy(self.run)
        if endpoint.endswith('/actions/workflows/50'):return {'id':50,'path':WORKFLOW,'state':'active'}
        if '/actions/runs?' in endpoint:return {'total_count':1,'workflow_runs':[deepcopy(self.run)]}
        raise AssertionError('Unexpected endpoint '+endpoint)


class ExecutionSource(unittest.TestCase):
    def test_divergent_execution_trees_fail_and_refreshed_heads_pass(self):
        global WORKFLOW, BEFORE, AFTER, COMPOSITE
        for case in ('main-only-workflow-job', 'main-only-composite-code', 'main-only-documentation'):
            with self.subTest(case=case):
                WORKFLOW='.github/workflows/codeql.yml' if case=='main-only-workflow-job' else '.github/workflows/build.yml'
                BEFORE=(SOURCE/WORKFLOW).read_text()
                pin=re.search(r'actions/checkout@([0-9a-f]{40}) # (v[0-9.]+)',BEFORE)
                self.assertIsNotNone(pin)
                AFTER=BEFORE.replace(pin[0], 'actions/checkout@'+NEW+' # v99.0.1')
                COMPOSITE=(SOURCE/ACTION).read_text()
                native=Native(case)
                self.addCleanup(native.directory.cleanup)
                context=dep.inspect(native,dep.REPOSITORY,native.pull)
                self.assertTrue(dep.classify(native,context))
                self.assertNotEqual(context['mergeBase'],context['base'])
                merged=native.git('show',native.merge+':'+(WORKFLOW if case=='main-only-workflow-job' else ACTION))
                if case=='main-only-workflow-job':
                    self.assertIn('contents: write',merged)
                    self.assertIn('id-token: write',merged)
                    self.assertIn('secrets.FIXTURE_ONLY_SECRET',merged)
                elif case=='main-only-composite-code':
                    self.assertIn('base-only-code-never-executed',merged)
                    import governed_tree
                    self.assertEqual(governed_tree.compare(native,dep.REPOSITORY,native.merge,native.head,{WORKFLOW}),[WORKFLOW])
                with self.assertRaisesRegex(ValueError,'current main included'):
                    adm.approve(adm.policy(),7,native.head,[40],api=native,post=native.posts.append)
                self.assertEqual(native.posts,[])
                # Refresh by incorporating actual main; the synthetic merge
                # tree now equals the PR head tree, including local actions.
                native.head=native.merge
                native.pull['head']['sha']=native.head
                native.run['head_sha']=native.head
                context=dep.inspect(native,dep.REPOSITORY,native.pull)
                self.assertEqual(context['mergeBase'],context['base'])
                self.assertEqual(native.git('merge-tree','--write-tree',native.base,native.head),
                                 native.git('rev-parse',native.head+'^{tree}'))
                result=adm.approve(adm.policy(),7,native.head,[40],api=native,post=native.posts.append)
                self.assertEqual(result['runs'][0]['status'],'execution-approved')
                self.assertEqual(native.posts,['repos/'+dep.REPOSITORY+'/actions/runs/40/approve'])
                # This is ancestry/source binding, not general privilege
                # scanning of unsafe code already trusted in current main.


if __name__=='__main__':
    unittest.main()
