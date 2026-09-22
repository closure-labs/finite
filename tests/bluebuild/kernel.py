#!/usr/bin/env python3
"""Check that kernel replacement failures preserve the installed kernel."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MOCK = '''#!/usr/bin/env python3
import json,os,sys,pathlib
name=pathlib.Path(sys.argv[0]).name
args=sys.argv[1:]
root=pathlib.Path(os.environ['TEST_ROOT'])
lock=json.loads((root/'payload/kernel-next/kernel-next.json').read_text())
release=lock['release']
with (root/'calls.jsonl').open('a') as f: f.write(json.dumps([name,*args])+'\\n')
if name=='rpm':
 if args[0]=='-qp':
  package=next(p for p in lock['packages'] if p['file']==pathlib.Path(args[-1]).name)
  print(package['name'] if args[2]=='%{NAME}' else release,end='')
 elif args[0]=='-q' and '--qf' not in args:
  sys.exit(1) # no optional build-only packages in this fixture
 else:
  package=args[-1]
  if '%{NAME}-' in args[2]:
   print(package+'-'+release+'\\t'+release)
   if not (root/'old-removed').exists(): print(package+'-old\\told')
  else: print(release)
elif name=='dnf5':
 if 'install' in args:
  if os.environ.get('INSTALL_FAIL'): sys.exit(1)
  (root/'installed').touch()
  current=root/'modules'/release
  current.mkdir()
  (current/'vmlinuz').write_bytes(b'kernel')
 if 'remove' in args:
  assert (root/'installed').exists(), 'removed old kernel before replacement'
  (root/'old-removed').touch()
elif name=='depmod':
 if not os.environ.get('MISSING_MODULE_INDEX'):
  (root/'modules'/release/'modules.dep').write_text('fixture.ko:')
elif name=='modinfo':
 field=args[args.index('-F')+1]
 if os.environ.get('MISSING_MODULE'): sys.exit(1)
 print({'filename':'/lib/modules/'+release+'/kernel/fixture.ko.xz','intree':'Y','signer':'Fedora kernel signing key'}[field])
elif name=='rpmkeys':
 if os.environ.get('BAD_RPM_SIGNATURE'): sys.exit(1)
 if '--checksig' in args:
  print('Header SHA256 digest: OK' if os.environ.get('UNSIGNED_RPM') else 'RSA signature: OK')
'''

class KernelReplacement(unittest.TestCase):
    def run_kernel(self, tamper=False, **extra):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        inherited=root/'modules'/'old'
        inherited.mkdir(parents=True)
        (inherited/'initramfs.img').write_bytes(b'inherited initramfs')
        kernel=root/'payload/kernel-next'
        kernel.mkdir(parents=True)
        lock=json.loads((ROOT/'sources/kernel-next.json').read_text())
        (kernel/'kernel-policy.json').write_bytes((ROOT/'sources/kernel-policy.json').read_bytes())
        (kernel/'kernel-signing.pub').write_bytes((ROOT/'sources/fedora-45.pub').read_bytes())
        for package in lock['packages']:
            data=package['name'].encode()
            package['sha256']=hashlib.sha256(data).hexdigest()
            (kernel/package['file']).write_bytes(data)
        (kernel/'kernel-next.json').write_text(json.dumps(lock))
        if tamper: (kernel/lock['packages'][0]['file']).write_bytes(b'corrupt')
        bindir=root/'bin'
        bindir.mkdir()
        for name in ['rpm','rpmkeys','dnf5','depmod','modinfo']:
            tool=bindir/name
            tool.write_text(MOCK.replace('#!/usr/bin/env python3','#!'+sys.executable,1))
            tool.chmod(0o755)
        env=dict(os.environ,PATH=str(bindir)+':'+os.environ['PATH'],CONFIG_DIRECTORY=str(root),TEST_ROOT=str(root),**extra)
        # Redirect only the module tree; exercise actual cleanup on a filesystem
        # fixture that retains generated files after the mocked RPM removal.
        script=root/'kernel-next.sh'
        script.write_text((ROOT/'files/scripts/kernel-next.sh').read_text().replace(
            'modules_root=/usr/lib/modules', 'modules_root='+shlex.quote(str(root/'modules'))))
        result=subprocess.run(['bash',str(script)],cwd=root,env=env,capture_output=True,text=True)
        log=root/'calls.jsonl'
        calls=[json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
        return result,calls,root/'modules'

    def test_old_kernel_removed_only_after_complete_install(self):
        result,calls,modules=self.run_kernel()
        self.assertEqual(result.returncode,0,result.stderr)
        install=next(i for i,c in enumerate(calls) if c[:3]==['dnf5','-y','install'])
        remove=next(i for i,c in enumerate(calls) if c[:3]==['dnf5','-y','remove'])
        self.assertLess(install,remove)
        self.assertEqual(sum(c.endswith('.rpm') for c in calls[install]),5)
        self.assertEqual(len([c for c in calls if c[0]=='modinfo']),15)
        release=json.loads((ROOT/'sources/kernel-next.json').read_text())['release']
        self.assertEqual([p.name for p in modules.iterdir()],[release])
        self.assertEqual((modules/release/'vmlinuz').read_bytes(),b'kernel')
        self.assertTrue((modules/release/'modules.dep').is_file())

    def test_corrupt_payload_never_changes_installed_packages(self):
        result,calls,modules=self.run_kernel(tamper=True)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(c[0]=='dnf5' for c in calls))
        self.assertTrue((modules/'old'/'initramfs.img').is_file())

    def test_failed_install_never_removes_old_kernel(self):
        result,calls,modules=self.run_kernel(INSTALL_FAIL='1')
        self.assertNotEqual(result.returncode,0)
        self.assertTrue(any(c[:3]==['dnf5','-y','install'] for c in calls))
        self.assertFalse(any(c[:3]==['dnf5','-y','remove'] for c in calls))
        self.assertTrue((modules/'old'/'initramfs.img').is_file())

    def test_missing_required_module_rejects_image(self):
        result,_,modules=self.run_kernel(MISSING_MODULE='1')
        self.assertNotEqual(result.returncode,0)
        self.assertTrue((modules/'old'/'initramfs.img').is_file())

    def test_missing_replacement_index_preserves_inherited_tree(self):
        result,_,modules=self.run_kernel(MISSING_MODULE_INDEX='1')
        self.assertNotEqual(result.returncode,0)
        self.assertTrue((modules/'old'/'initramfs.img').is_file())

    def test_untrusted_or_unsigned_rpm_never_changes_installed_packages(self):
        for failure in ['BAD_RPM_SIGNATURE', 'UNSIGNED_RPM']:
            result,calls,_=self.run_kernel(**{failure:'1'})
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(any(call[0]=='dnf5' for call in calls))

if __name__=='__main__': unittest.main()
