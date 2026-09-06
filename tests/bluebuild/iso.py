#!/usr/bin/env python3
"""Exercise the ISO boundary without downloading images or running containers."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/bluebuild/iso.sh'
DIGEST = 'sha256:' + 'a' * 64
MOCK = '''#!/usr/bin/env python3
import hashlib,json,os,sys,pathlib
name=pathlib.Path(sys.argv[0]).name
args=sys.argv[1:]
with open('calls.jsonl','a') as f: f.write(json.dumps([name,*args])+'\\n')
if name=='cosign':
 if os.environ.get('BAD_SIGNATURE'): sys.exit(1)
 print('[]')
elif name=='skopeo':
 if args[0]=='list-tags': print('{"Tags": ["bluefin-generic"]}')
 elif args[0]=='inspect':
  digest=os.environ['DIGEST']
  if os.environ.get('MOVED_CHANNEL') and args[-1].endswith(':bluefin-generic'): digest='sha256:'+'b'*64
  if '--format' in args: print(digest)
  else: print(json.dumps({'Digest':digest,'Labels':{'io.finite.profile':'bluefin-next' if os.environ.get('MISMATCH_PROFILE') else 'bluefin-generic'}}))
elif name=='sudo':
 assert args[0:2]==['bluebuild','generate-iso']
 assert args[args.index('--run-driver')+1]=='docker'
 assert args[args.index('--variant')+1]=='kinoite'
 assert args[-2]=='image' and ':i' in args[-1] and '@' not in args[-1]
 path=pathlib.Path(args[args.index('--output-dir')+1])/args[args.index('--iso-name')+1]
 path.write_bytes(b'fixture ISO')
elif name=='docker':
 if args[0]=='build':
  assert pathlib.Path(args[args.index('--file')+1]).is_file()
  assert pathlib.Path(args[-1],'install_finite_fstab').is_file()
 elif args[0]=='inspect':
  if '--format' in args: print('sha256:'+'c'*64)
  else:
   lock=json.loads(pathlib.Path('sources/bluebuild-installer.json').read_text())
   print(json.dumps([{'Config':{'Labels':{'org.opencontainers.image.version':lock['version'],'org.opencontainers.image.revision':'wrong' if os.environ.get('BAD_INSTALLER_LABEL') else lock['revision']}}}]))
 elif args[0]=='run':
  if os.environ.get('BAD_INSTALLER_CLEANUP'): sys.exit(1)
  if 'sha256sum' in args:
   value=hashlib.sha256(pathlib.Path('files/installer/install_finite_fstab').read_bytes()).hexdigest()
   print(('bad' if os.environ.get('BAD_INSTALLER_HOOK') else value)+'  hook')
'''

class IsoBoundary(unittest.TestCase):
    def run_iso(self, **extra):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        bindir = root / 'bin'
        bindir.mkdir()
        for name in ['cosign','skopeo','sudo','docker']:
            tool = bindir / name
            tool.write_text(MOCK.replace("#!/usr/bin/env python3", "#!" + sys.executable, 1))
            tool.chmod(0o755)
        (root/'sources').mkdir()
        (root/'sources/bluebuild-installer.json').write_text((SCRIPT.parents[2]/'sources/bluebuild-installer.json').read_text())
        shutil.copytree(SCRIPT.parents[2]/'files/installer', root/'files/installer')
        env = dict(os.environ, PATH=str(bindir)+':'+os.environ['PATH'], DIGEST=DIGEST,
                   GITHUB_ACTIONS='true', GITHUB_REPOSITORY='closure-labs/finite',
                   GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='2', GITHUB_SHA='d'*40, **extra)
        result = subprocess.run(['bash',str(SCRIPT),'bluefin-generic',DIGEST],cwd=root,env=env,capture_output=True,text=True)
        self.assertTrue((root/'calls.jsonl').exists(), result.stderr)
        calls=[json.loads(l) for l in (root/'calls.jsonl').read_text().splitlines()]
        return root,result,calls

    def test_verified_digest_uses_unique_tag_and_records_channel(self):
        root,result,calls=self.run_iso()
        self.assertEqual(result.returncode,0,result.stderr)
        record=json.loads((root/'.bluebuild/iso/installation.json').read_text())
        self.assertEqual(record['image'],'ghcr.io/closure-labs/finite@'+DIGEST)
        self.assertRegex(record['installationTag'],r':i[a-f0-9]{16}$')
        self.assertLessEqual(len('finite-x86_64-'+record['installationTag'].split(':')[-1]),32)
        self.assertEqual(record['updateChannel'],'ghcr.io/closure-labs/finite:bluefin-generic')
        self.assertEqual(record['installer']['version'],'v1.5.0')
        self.assertIn('@sha256:',record['installer']['resolvedImage'])
        build=next(c for c in calls if c[:2]==['docker','build'])
        self.assertEqual(build[build.index('--build-arg')+1],'INSTALLER='+record['installer']['resolvedImage'])
        self.assertEqual(build[build.index('--tag')+1],record['installer']['cliAlias'])
        self.assertEqual(record['installer']['postInstallHook']['sha256'],hashlib.sha256((root/'files/installer/install_finite_fstab').read_bytes()).hexdigest())
        self.assertEqual(record['installer']['finiteRevision'],'d'*40)
        self.assertFalse(any(c[:2]==['docker','push'] for c in calls))
        copy=next(c for c in calls if c[:2]==['skopeo','copy'])
        self.assertIn('--preserve-digests',copy)
        self.assertIn('--all',copy)
        self.assertTrue((root/'.bluebuild/iso/SHA256SUMS').is_file())

    def test_bad_signature_never_copies_or_builds(self):
        _,result,calls=self.run_iso(BAD_SIGNATURE='1')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(c[:2]==['skopeo','copy'] or c[0]=='sudo' for c in calls))
        self.assertFalse(any(c[0]=='docker' for c in calls))

    def test_installer_must_match_its_lock_and_retain_the_policy_loader(self):
        for failure in ['BAD_INSTALLER_LABEL','BAD_INSTALLER_CLEANUP']:
            with self.subTest(failure=failure):
                _,result,calls=self.run_iso(**{failure:'1'})
                self.assertNotEqual(result.returncode,0)
                self.assertFalse(any(c[:2] in [['skopeo','copy'],['docker','build']] or c[0]=='sudo' for c in calls))

    def test_installer_hook_must_match_the_reviewed_source(self):
        _,result,calls=self.run_iso(BAD_INSTALLER_HOOK='1')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(c[:2]==['skopeo','copy'] or c[0]=='sudo' for c in calls))

    def test_moved_channel_keeps_the_requested_verified_digest(self):
        root,result,calls=self.run_iso(MOVED_CHANNEL='1')
        self.assertEqual(result.returncode,0,result.stderr)
        record=json.loads((root/'.bluebuild/iso/installation.json').read_text())
        self.assertEqual(record['image'],'ghcr.io/closure-labs/finite@'+DIGEST)
        self.assertFalse(any(c[:2]==['skopeo','inspect'] and c[-1].endswith(':bluefin-generic') for c in calls))

    def test_wrong_profile_never_copies_or_builds(self):
        _,result,calls=self.run_iso(MISMATCH_PROFILE='1')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(c[:2]==['skopeo','copy'] or c[0]=='sudo' for c in calls))

if __name__=='__main__': unittest.main()
