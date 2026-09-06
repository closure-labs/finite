#!/usr/bin/env python3
"""Check installer root finalization without touching the host filesystem."""
import os
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


if __name__ == "__main__":
    unittest.main()
