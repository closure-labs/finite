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
old_release='7.2.5-200.fc44.x86_64'
zfs_packages=['kmod-zfs','zfs','python3-pyzfs']
with (root/'calls.jsonl').open('a') as f: f.write(json.dumps([name,*args])+'\\n')
if name=='rpm':
 if args[0]=='-qa':
  for package in ['kernel','kernel-core','kernel-modules-core','kernel-modules','kernel-modules-extra']:
   if (root/'installed').exists(): print(package+'\\t0:'+release.rsplit('.',1)[0]+'\\tx86_64')
   if not (root/'old-removed').exists(): print(package+'\\t0:'+old_release.rsplit('.',1)[0]+'\\tx86_64')
  print('bootc\\t0:1.13.0-1.fc44\\tx86_64')
  print('podman\\t0:6.4.1-1.fc44\\tx86_64')
  if not (root/'nvidia-erased').exists() and (os.environ.get('FOREIGN_NVIDIA') or any(k.startswith('ERASE_NVIDIA_ON_') for k in os.environ)):
   print('kmod-nvidia\\t0:2.4.4-1.fc44\\tx86_64')
  if os.environ.get('HOST_ZFS'):
   for package in ['libnvpair3','libuutil3','libzfs7','libzpool7']:
    if not (root/'library-erased').exists(): print(package+'\\t0:2.4.4-1.fc44\\tx86_64')
   if not (root/'zfs-removed').exists():
    for package in zfs_packages:
     print(package+'\\t0:2.4.4-1.fc44\\t'+('noarch' if package=='python3-pyzfs' else 'x86_64'))
  if os.environ.get('REINTRODUCE_ZFS_ON_INSTALL') and (root/'installed').exists():
   print('kmod-zfs\\t0:3.0.0-1.fc44\\tx86_64')
 elif args[0]=='-qf':
  if os.environ.get('OWNERSHIP_PROBE_ERROR'):
   print('RPM database error'); sys.exit(2)
  if pathlib.Path(args[-1]).name=='nvidia.ko':
   print('kmod-nvidia')
  else:
   print('file '+args[-1]+' is not owned by any package'); sys.exit(1)
 elif args[0]=='-qp':
  package=next(p for p in lock['packages'] if p['file']==pathlib.Path(args[-1]).name)
  print(package['name'] if args[2]=='%{NAME}' else release,end='')
 elif args[0]=='-q' and '--qf' not in args:
  if args[-1]=='kmod-v4l2loopback' and os.environ.get('ERASE_NVIDIA_ON_CLEANUP'): sys.exit(0)
  if args[-1] in zfs_packages and os.environ.get('HOST_ZFS') and not (root/'zfs-removed').exists(): sys.exit(0)
  sys.exit(1) # no optional build-only packages in this fixture
 else:
  package=args[-1]
  if '%{NAME}-' in args[2]:
   print(package+'-'+release+'\\t'+release)
   if not (root/'old-removed').exists(): print(package+'-'+old_release+'\\t'+old_release)
  else: print(release if (root/'installed').exists() else old_release)
elif name=='dnf5':
 erase_nvidia=False
 if 'install' in args:
  if os.environ.get('INSTALL_FAIL'): sys.exit(1)
  (root/'installed').touch()
  current=root/'modules'/release
  current.mkdir()
  (current/'vmlinuz').write_bytes(b'kernel')
  erase_nvidia=bool(os.environ.get('ERASE_NVIDIA_ON_INSTALL'))
 if 'remove' in args:
  if 'kmod-v4l2loopback' in args or 'kmod-zfs' in args:
   erase_nvidia=bool(os.environ.get('ERASE_NVIDIA_ON_CLEANUP'))
   if 'kmod-zfs' in args:
    assert all(package in args for package in zfs_packages)
    assert '--disable-repo=*' in args and '--no-autoremove' in args
    (root/'zfs-removed').touch()
    for name in ['spl.ko','zfs.ko']:
     (root/'modules'/old_release/'extra/zfs'/name).unlink()
    if os.environ.get('ERASE_ZFS_SHARED_LIBRARY'): (root/'library-erased').touch()
  else:
   assert (root/'installed').exists(), 'removed old kernel before replacement'
   (root/'old-removed').touch()
   erase_nvidia=bool(os.environ.get('ERASE_NVIDIA_ON_STALE_REMOVE'))
 if erase_nvidia:
  (root/'nvidia-erased').touch()
  (root/'modules'/old_release/'extra/nvidia/nvidia.ko').unlink()
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
        inherited=root/'modules'/'7.2.5-200.fc44.x86_64'
        inherited.mkdir(parents=True)
        (inherited/'initramfs.img').write_bytes(b'inherited initramfs')
        if extra.get('FOREIGN_NVIDIA') or any(k.startswith('ERASE_NVIDIA_ON_') for k in extra):
            zfs=inherited/'extra/nvidia'
            zfs.mkdir(parents=True)
            (zfs/'nvidia.ko').write_bytes(b'retained NVIDIA module')
        if extra.get('HOST_ZFS'):
            zfs=inherited/'extra/zfs'
            zfs.mkdir(parents=True)
            for name in ('spl.ko','zfs.ko'):
                (zfs/name).write_bytes(b'owned ZFS module')
        if extra.get('UNEXPECTED_MODULE'):
            (inherited/'manual.ko').write_bytes(b'unowned manual module')
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
        scripts=root/'scripts'
        scripts.mkdir()
        (scripts/'kernel-module-prune.py').write_bytes((ROOT/'files/scripts/kernel-module-prune.py').read_bytes())
        (scripts/'security-remediate.py').write_bytes((ROOT/'files/scripts/security-remediate.py').read_bytes())
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
        remove=next(i for i,c in enumerate(calls) if c[0]=='dnf5' and 'remove' in c)
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
        self.assertTrue((modules/'7.2.5-200.fc44.x86_64'/'initramfs.img').is_file())

    def test_failed_install_never_removes_old_kernel(self):
        result,calls,modules=self.run_kernel(INSTALL_FAIL='1')
        self.assertNotEqual(result.returncode,0)
        self.assertTrue(any(c[:3]==['dnf5','-y','install'] for c in calls))
        self.assertFalse(any(c[0]=='dnf5' and 'remove' in c for c in calls))
        self.assertTrue((modules/'7.2.5-200.fc44.x86_64'/'initramfs.img').is_file())

    def test_missing_required_module_rejects_image(self):
        result,_,modules=self.run_kernel(MISSING_MODULE='1')
        self.assertNotEqual(result.returncode,0)
        self.assertTrue((modules/'7.2.5-200.fc44.x86_64'/'initramfs.img').is_file())

    def test_missing_replacement_index_preserves_inherited_tree(self):
        result,_,modules=self.run_kernel(MISSING_MODULE_INDEX='1')
        self.assertNotEqual(result.returncode,0)
        self.assertTrue((modules/'7.2.5-200.fc44.x86_64'/'initramfs.img').is_file())

    def test_next_preserves_foreign_owned_nvidia_module(self):
        result,calls,modules=self.run_kernel(FOREIGN_NVIDIA='1')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Still installed package owns stale module file',result.stderr)
        self.assertEqual((modules/'7.2.5-200.fc44.x86_64'/'extra/nvidia/nvidia.ko').read_bytes(),b'retained NVIDIA module')
        self.assertTrue((modules/'7.2.5-200.fc44.x86_64'/'initramfs.img').exists())
        self.assertFalse(any('kmod-nvidia' in call for call in calls if call[0]=='dnf5'))

    def test_next_rejects_unowned_manual_modules(self):
        result,_,modules=self.run_kernel(UNEXPECTED_MODULE='1')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Unreviewed unowned file',result.stderr)
        self.assertTrue((modules/'7.2.5-200.fc44.x86_64'/'manual.ko').exists())

    def test_next_rejects_ownership_probe_failure(self):
        result,_,modules=self.run_kernel(OWNERSHIP_PROBE_ERROR='1')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Cannot establish stale module file ownership',result.stderr)
        self.assertTrue((modules/'7.2.5-200.fc44.x86_64'/'initramfs.img').exists())

    def test_every_solver_operation_rejects_nvidia_package_and_file_erasure(self):
        for failure in ('ERASE_NVIDIA_ON_CLEANUP','ERASE_NVIDIA_ON_INSTALL','ERASE_NVIDIA_ON_STALE_REMOVE'):
            with self.subTest(operation=failure):
                result,calls,modules=self.run_kernel(**{failure:'1'})
                self.assertNotEqual(result.returncode,0)
                self.assertIn('Unapproved package mutation during next kernel transaction: kmod-nvidia',result.stderr)
                self.assertTrue((modules/'7.2.5-200.fc44.x86_64'/'initramfs.img').exists())
                self.assertFalse((modules/'7.2.5-200.fc44.x86_64'/'extra/nvidia/nvidia.ko').exists())
                # Unlike file ownership alone, the inventory guard catches a
                # solver that erased both the RPM and its files. No later
                # deletion operation may run after that failed check.
                mutations=[call for call in calls if call[0]=='dnf5']
                self.assertEqual(len(mutations), {'ERASE_NVIDIA_ON_CLEANUP':1,
                                                 'ERASE_NVIDIA_ON_INSTALL':1,
                                                 'ERASE_NVIDIA_ON_STALE_REMOVE':2}[failure])

    def test_next_removes_authorized_zfs_support_before_install(self):
        result,calls,modules=self.run_kernel(HOST_ZFS='1')
        self.assertEqual(result.returncode,0,result.stderr)
        cleanup=next(i for i,c in enumerate(calls) if c[0]=='dnf5' and 'kmod-zfs' in c)
        install=next(i for i,c in enumerate(calls) if c[:3]==['dnf5','-y','install'])
        self.assertLess(cleanup,install)
        self.assertTrue(all(name in calls[cleanup] for name in ('kmod-zfs','zfs','python3-pyzfs')))
        self.assertFalse(any(name in calls[cleanup] for name in ('libnvpair3','libuutil3','libzfs7','libzpool7')))
        self.assertFalse(list(modules.glob('*/extra/zfs/*.ko')))
        self.assertEqual(sum('--checksig' in c for c in calls[:cleanup]),5)

    def test_next_authentication_failure_preserves_zfs(self):
        result,calls,modules=self.run_kernel(HOST_ZFS='1',BAD_RPM_SIGNATURE='1')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(c[0]=='dnf5' for c in calls))
        self.assertTrue((modules/'7.2.5-200.fc44.x86_64'/'extra/zfs/spl.ko').exists())

    def test_next_cannot_erase_protected_zfs_shared_libraries(self):
        result,_,modules=self.run_kernel(HOST_ZFS='1',ERASE_ZFS_SHARED_LIBRARY='1')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Unapproved package mutation during next kernel transaction: lib',result.stderr)
        self.assertTrue((modules/'7.2.5-200.fc44.x86_64'/'initramfs.img').exists())

    def test_next_cannot_reintroduce_zfs_after_cleanup(self):
        result,_,modules=self.run_kernel(HOST_ZFS='1',REINTRODUCE_ZFS_ON_INSTALL='1')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Authorized ZFS transition must remove the package',result.stderr)
        self.assertTrue((modules/'7.2.5-200.fc44.x86_64'/'initramfs.img').exists())

    def test_untrusted_or_unsigned_rpm_never_changes_installed_packages(self):
        for failure in ['BAD_RPM_SIGNATURE', 'UNSIGNED_RPM']:
            result,calls,_=self.run_kernel(**{failure:'1'})
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(any(call[0]=='dnf5' for call in calls))

if __name__=='__main__': unittest.main()
