#!/usr/bin/env python3
"""Prevent old release and recovery routes from bypassing unified release approval."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('legacy_boundary', ROOT / 'scripts/ci/legacy-release-boundary.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
CONTEXT = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite', 'GITHUB_REF': 'refs/heads/main'}


def response(mode):
    data = json.dumps({'schema': 1, 'mode': mode}).encode()
    document = {'type': 'file', 'encoding': 'base64', 'size': len(data), 'content': base64.b64encode(data).decode()}
    return SimpleNamespace(returncode=0, stdout=json.dumps(document))


class LegacyBoundary(unittest.TestCase):
    def test_existing_legacy_modes_remain_usable(self):
        for mode in mod.LEGACY_MODES:
            self.assertEqual(mod.parse_policy(json.dumps({'schema': 1, 'mode': mode})), mode)
        self.assertEqual(mod.parse_policy('{"schema":1}'), 'fixable-severity')

    def test_new_unknown_and_ambiguous_policy_cannot_authorize_legacy_release(self):
        for document in ('{"schema":1,"mode":"maintainer-decision"}', '{"schema":1,"mode":"new-mode"}',
                         '{"schema":true}', '{"schema":1,"mode":"fixable-severity","mode":"maintainer-decision"}'):
            with self.assertRaises(ValueError):
                mod.parse_policy(document)

    def test_checked_out_policy_must_exist_be_regular_and_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'automation/security/image-policy.json'
            with self.assertRaises(ValueError):
                mod.require_legacy_policy(root)
            path.parent.mkdir(parents=True)
            path.write_text('{"schema":1,"mode":"desktop-critical-only"}')
            self.assertEqual(mod.require_legacy_policy(root), 'desktop-critical-only')
            target = root / 'target'
            path.rename(target)
            path.symlink_to(target)
            with self.assertRaises(ValueError):
                mod.require_legacy_policy(root)

    def test_current_main_cutover_stops_a_run_with_old_checked_out_policy(self):
        with patch.dict(os.environ, CONTEXT, clear=True), patch.object(mod.subprocess, 'run', return_value=response('maintainer-decision')):
            with self.assertRaises(ValueError):
                mod.require_current_legacy_policy()
        with patch.dict(os.environ, CONTEXT, clear=True), patch.object(mod.subprocess, 'run', return_value=response('desktop-critical-only')):
            self.assertEqual(mod.require_current_legacy_policy(), 'desktop-critical-only')

    def test_api_failure_and_wrong_context_fail_closed(self):
        with patch.dict(os.environ, CONTEXT, clear=True), patch.object(mod.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='')):
            with self.assertRaises(ValueError):
                mod.require_current_legacy_policy()
        with patch.dict(os.environ, {**CONTEXT, 'GITHUB_REF': 'refs/heads/feature'}, clear=True), patch.object(mod.subprocess, 'run') as api:
            with self.assertRaises(ValueError):
                mod.require_current_legacy_policy()
            api.assert_not_called()

    def test_preparation_and_signers_guard_before_credentials_and_tools(self):
        for name, preparation in (('release.yml', 'release'), ('release-recovery.yml', 'verify-prepared')):
            workflow = (ROOT / '.github/workflows' / name).read_text()
            self.assertEqual(workflow.count('name: Enforce legacy release boundary'), 2)
            prepare, signer = workflow.split('\n  sign-release:', 1)
            self.assertLess(prepare.index('legacy-release-boundary.py'), prepare.index('uses: hastd/free-disk-space'))
            self.assertLess(signer.index('legacy-release-boundary.py'), signer.index('uses: $/.github/actions/setup-cosign'))
            self.assertLess(signer.index('name: Recheck current main policy before signing credentials'), signer.index('COSIGN_PRIVATE_KEY:'))
            self.assertLess(signer.index('name: Recheck current main policy before publication credentials'), signer.index('MERGE_QUEUE_TOKEN:'))
            self.assertIn('automation/security/', signer)
            self.assertIn('scripts/ci/', signer)

    def test_only_bounded_reuse_service_receives_public_bot_login(self):
        workflow = (ROOT / '.github/workflows/publication.yml').read_text()
        security = workflow.split('\n  security:', 1)[1].split('\n  attest:', 1)[0]
        self.assertIn('FINITE_REVIEW_BOT_LOGIN: ${{ vars.FINITE_REVIEW_BOT_LOGIN }}', security)
        self.assertIn('GITHUB_SHA,FINITE_REVIEW_BOT_LOGIN', security)
        self.assertIn('--setenv=FINITE_REVIEW_BOT_LOGIN', security)
        scanner = (ROOT / 'scripts/bluebuild/security-run.sh').read_text()
        self.assertNotIn('--setenv=FINITE_REVIEW_BOT_LOGIN', scanner)


if __name__ == '__main__':
    unittest.main()
