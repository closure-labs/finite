#!/usr/bin/env python3
"""Production signer restrictions must reject wildcard, tag and broad access."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('signer', ROOT / 'scripts/bluebuild/provision-boot-signer.py')
signer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signer)


class BootSigner(unittest.TestCase):
    def test_only_main_branch_is_admitted(self):
        signer.validate_policy({'deployment_branch_policy': {'protected_branches': False, 'custom_branch_policies': True}},
                               {'branch_policies': [{'name': 'main', 'type': 'branch'}]})

    def test_unrestricted_and_tag_deployments_are_rejected(self):
        for branches in [[], [{'name': '*', 'type': 'branch'}], [{'name': 'main', 'type': 'tag'}],
                         [{'name': 'main', 'type': 'branch'}, {'name': 'trial', 'type': 'branch'}]]:
            with self.subTest(branches=branches), self.assertRaises(ValueError):
                signer.validate_policy({'deployment_branch_policy': {'protected_branches': False, 'custom_branch_policies': True}},
                                       {'branch_policies': branches})
        with self.assertRaises(ValueError):
            signer.validate_policy({'deployment_branch_policy': None}, {'branch_policies': [{'name': 'main', 'type': 'branch'}]})


if __name__ == '__main__':
    unittest.main()
