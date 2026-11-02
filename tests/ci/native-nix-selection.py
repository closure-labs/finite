import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/ci'))
spec = importlib.util.spec_from_file_location('native_selector', ROOT/'scripts/ci/native-nix-selection.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


class Selection(unittest.TestCase):
    def test_missing_comparison_requires_vm(self):
        self.assertTrue(module.required(None))

    def test_native_input_groups_require_vm(self):
        for path in ('flake.lock', 'flake.nix', 'lib/native-nix-backport.nix',
            'patches/nix/completed-resume-416.patch', 'sources/determinate-nix.json',
            'files/scripts/lib/install-determinate-nix.sh',
            'files/system/usr/libexec/finite/install-native-nix-runtime',
            'files/system/usr/lib/systemd/system/nix-daemon.service',
            'scripts/bluebuild/vm-acceptance.sh', 'lib/image-payload.nix'):
            with self.subTest(path=path): self.assertTrue(module.required([path]))

    def test_unrelated_documentation(self):
        self.assertFalse(module.required(['docs/README.md']))

    def test_mixed_paths_remain_required(self):
        self.assertTrue(module.required(['docs/README.md', 'flake.lock']))


if __name__ == '__main__': unittest.main()
