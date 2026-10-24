#!/usr/bin/env python3
"""Check installer root finalization without touching the host filesystem."""
import os
import importlib.util
import hashlib
import json
from unittest.mock import patch
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
FSTAB = """# Keep installer comments
UUID=root / btrfs subvol=root,compress=zstd:1,ro 0 0
UUID=boot /boot ext4 defaults 1 2
UUID=efi /boot/efi vfat umask=0077 0 2
UUID=root /var/home btrfs subvol=home,compress=zstd:1 0 0
"""


class InstallerFinalization(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for directory in ["etc", "usr/bin", "boot/loader/entries", "bin"]:
            (self.root / directory).mkdir(parents=True)
        self.fstab = self.root / "etc/fstab"
        self.fstab.write_text(FSTAB)
        self.fstab.chmod(0o644)
        (self.root / "usr/bin/bootc").touch(mode=0o755)
        self.entry = self.root / "boot/loader/entries/ostree-1.conf"
        self.entry.write_text("options root=UUID=root rootflags=subvol=root rw ostree=/ostree/boot.1/fixture\n")
        restorecon = self.root / "bin/restorecon"
        restorecon.write_text("#!" + sys.executable + "\nimport sys\nassert sys.argv[1].endswith('/etc/fstab')\n")
        restorecon.chmod(0o755)

    def run_hook(self):
        env = dict(os.environ, PATH=str(self.root / "bin") + ":" + os.environ["PATH"])
        return subprocess.run(
            ["bash", str(ROOT / "files/installer/install_finite_fstab"), str(self.root)],
            env=env, capture_output=True, text=True,
        )

    def test_preserves_other_mounts_mode_and_boot_entries(self):
        before = self.entry.read_bytes()
        result = self.run_hook()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fstab.read_text(), "".join(FSTAB.splitlines(keepends=True)[0:1] + FSTAB.splitlines(keepends=True)[2:]))
        self.assertEqual(self.fstab.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.entry.read_bytes(), before)
        self.assertEqual(self.run_hook().returncode, 0)

    def test_missing_physical_root_argument_preserves_fstab(self):
        self.entry.write_text("options rootflags=subvol=root rw\n")
        self.assertNotEqual(self.run_hook().returncode, 0)
        self.assertEqual(self.fstab.read_text(), FSTAB)

    def test_missing_subvolume_argument_preserves_fstab(self):
        self.entry.write_text("options root=UUID=root rw\n")
        self.assertNotEqual(self.run_hook().returncode, 0)
        self.assertEqual(self.fstab.read_text(), FSTAB)

    def test_every_boot_entry_must_identify_the_correct_subvolume(self):
        (self.entry.parent / "ostree-2.conf").write_text("options root=UUID=root rootflags=subvol=wrong rw\n")
        self.assertNotEqual(self.run_hook().returncode, 0)
        self.assertEqual(self.fstab.read_text(), FSTAB)

    def test_missing_boot_entries_preserves_fstab(self):
        self.entry.unlink()
        self.assertNotEqual(self.run_hook().returncode, 0)
        self.assertEqual(self.fstab.read_text(), FSTAB)

    def test_root_without_subvolume_needs_only_root_argument(self):
        self.fstab.write_text(FSTAB.replace("btrfs subvol=root,compress=zstd:1,ro", "ext4 defaults"))
        self.entry.write_text("options root=UUID=root rw\n")
        self.assertEqual(self.run_hook().returncode, 0)
        self.assertNotIn(" / ", self.fstab.read_text())


class CompressionDiagnostic(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('installer_compression',ROOT/'scripts/bluebuild/installer-compression.py')
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.directory=Path(temporary.name)
        self.preset=self.directory/'preset';self.preset.write_bytes((ROOT/'files/installer/lorax-zstd.conf').read_bytes())
        self.target=self.directory/'lorax.conf';self.target.write_text('[lorax]\nlogdir = /custom\n[compression]\ntype = xz\nargs = \nbcj = on\n')

    def test_compression_merge_preserves_unrelated_settings_and_mode(self):
        self.target.chmod(0o640)
        self.module.merge(self.target,self.preset)
        self.assertEqual(self.module.read(self.target)['lorax']['logdir'],'/custom')
        self.assertEqual(self.target.stat().st_mode&0o777,0o640)
        self.assertEqual(self.module.verify(self.target),hashlib.sha256(self.target.read_bytes()).hexdigest())
        before=self.target.read_bytes();self.module.merge(self.target,self.preset)
        self.assertEqual(self.target.read_bytes(),before)

    def test_altered_presets_fail_without_changing_the_existing_config(self):
        raw=self.preset.read_text();before=self.target.read_bytes()
        for changed in (raw.replace('zstd','xz'),raw.replace('15','22'),raw.replace('off','on'),raw+'\n[other]\noption = value\n'):
            with self.subTest(preset=changed):
                self.preset.write_text(changed)
                with self.assertRaises(ValueError):self.module.merge(self.target,self.preset)
                self.assertEqual(self.target.read_bytes(),before)

    def test_installed_config_tampering_or_missing_fields_fail_verification(self):
        self.module.merge(self.target,self.preset);raw=self.target.read_text()
        for changed in (raw.replace('zstd','xz'),raw.replace('15','1'),raw.replace('bcj = off','bcj = on'),raw.replace('args = -Xcompression-level 15','')):
            self.target.write_text(changed)
            with self.assertRaises(ValueError):self.module.verify(self.target)


class CompressionCapability(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('installer_probe',ROOT/'scripts/bluebuild/installer-compression.py')
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.bin=self.root/'bin';self.bin.mkdir()
        # Simulate the older CLI: help options fail, while a real codec round
        # trip succeeds. Actual child processes exercise arguments and cleanup.
        script='#!'+sys.executable+'\n'+'''
import base64,json,os,pathlib,sys
args=sys.argv[1:]
with open(os.environ['PROBE_LOG'],'a') as log:log.write(json.dumps({'tool':pathlib.Path(sys.argv[0]).name,'args':args})+'\\n')
if '-help-comp' in args:sys.exit(1)
if pathlib.Path(sys.argv[0]).name=='mksquashfs':
    if os.environ.get('PROBE_FAILURE')=='pack':sys.exit(2)
    assert args[2:]==['-noappend','-comp','zstd','-Xcompression-level','15','-processors','1','-mem','64M','-no-progress']
    pathlib.Path(args[1]).write_bytes(base64.b64encode((pathlib.Path(args[0])/'probe').read_bytes()))
else:
    assert args[:3]==['-processors','1','-d']
    if os.environ.get('PROBE_FAILURE')=='unpack':sys.exit(2)
    output=pathlib.Path(args[3]);output.mkdir()
    payload=base64.b64decode(pathlib.Path(args[4]).read_bytes())
    (output/'probe').write_bytes(b'corrupt' if os.environ.get('PROBE_FAILURE')=='corrupt' else payload)
'''
        for name in ('mksquashfs','unsquashfs'):
            path=self.bin/name;path.write_text(script);path.chmod(0o755)

    def invoke(self,failure='',cli=False):
        env={'PATH':str(self.bin)+os.pathsep+os.environ['PATH'],'PROBE_LOG':str(self.root/'log'),'PROBE_FAILURE':failure}
        with patch.dict(os.environ,env):
            if cli:subprocess.run([sys.executable,str(ROOT/'scripts/bluebuild/installer-compression.py'),'probe'],check=True)
            else:self.module.probe()

    def paths(self):
        calls=[json.loads(line) for line in (self.root/'log').read_text().splitlines()]
        return calls,[Path(calls[0]['args'][0]).parent]

    def test_old_cli_succeeds_without_help_and_removes_probe_files(self):
        self.invoke(cli=True);calls,roots=self.paths()
        self.assertEqual([c['tool'] for c in calls],['mksquashfs','unsquashfs'])
        self.assertTrue(all(not p.exists() for p in roots))
        self.assertTrue(all('-help-comp' not in c['args'] for c in calls))

    def test_pack_unpack_and_integrity_failures_stop_and_clean_up(self):
        for failure in ('pack','unpack','corrupt'):
            with self.subTest(failure=failure):
                (self.root/'log').unlink(missing_ok=True)
                with self.assertRaises((subprocess.CalledProcessError,ValueError)):self.invoke(failure)
                calls,roots=self.paths()
                self.assertTrue(all(not p.exists() for p in roots))
                self.assertEqual(len(calls),1 if failure=='pack' else 2)

    def test_command_timeout_propagates_and_cleans_probe(self):
        def timeout(command,**kwargs):
            self.root.joinpath('timeout-root').write_text(str(Path(command[1]).parent))
            self.assertEqual(kwargs['timeout'],30)
            raise subprocess.TimeoutExpired(command,30)
        with patch.object(self.module.subprocess,'run',side_effect=timeout),self.assertRaises(subprocess.TimeoutExpired):self.module.probe()
        self.assertFalse(Path((self.root/'timeout-root').read_text()).exists())


if __name__ == "__main__":
    unittest.main()
