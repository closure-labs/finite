#!/usr/bin/env python3
"""Keep promoted stable kernel updates visible without widening the approved stream."""
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error
import xmlrpc.client

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('kernel_update', ROOT / 'scripts/ci/kernel-update.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
POLICY = {'fedora': 45, 'kojiTag': 'f45', 'stableUpdateTag': 'f45-updates', 'series': '7.2',
          'architecture': 'x86_64', 'keyId': 'f577861e', 'maxLagDays': 7}


def build(version='7.2.9', release='300.fc45', identity=10):
    return {'name': 'kernel', 'version': version, 'release': release, 'id': identity,
            'epoch': None, 'nvr': 'kernel-' + version + '-' + release,
            'completion_time': '2026-10-12 12:00:00'}


def encoded(value):
    return xmlrpc.client.dumps((value,), methodresponse=True, allow_none=True).encode()


class KernelLatest(unittest.TestCase):
    def query(self, base=None, stable=None, policy=None, raw=None, failure=None):
        calls = []
        responses = iter(raw if raw is not None else (encoded([base or build()]), encoded([] if stable is None else [stable])))
        def urlopen(request, timeout):
            parameters, method = xmlrpc.client.loads(request.data)
            calls.append((parameters, method, timeout, request.full_url))
            if failure and len(calls) == failure:
                raise urllib.error.URLError('unavailable')
            return io.BytesIO(next(responses))
        with patch.object(mod.urllib.request, 'urlopen', side_effect=urlopen):
            result = mod.latest(POLICY if policy is None else policy)
        return result, calls

    def test_queries_exact_base_and_stable_tags(self):
        result, calls = self.query()
        self.assertEqual(result, build())
        self.assertEqual([c[:3] for c in calls], [
            (('f45', None, 'kernel'), 'getLatestBuilds', 60),
            (('f45-updates', None, 'kernel'), 'getLatestBuilds', 60)])
        self.assertTrue(all(c[3] == 'https://koji.fedoraproject.org/kojihub' for c in calls))

    def test_promoted_stable_build_advances_patch_and_release_numerically(self):
        for stable in (build(release='301.fc45', identity=11), build('7.2.10', '301.fc45', 12),
                       build('7.2.9', '1000.fc45', 13)):
            with self.subTest(stable=stable):
                self.assertEqual(self.query(stable=stable)[0], stable)

    def test_base_can_remain_newer_than_stable(self):
        self.assertEqual(self.query(base=build('7.2.10'), stable=build('7.2.9'))[0], build('7.2.10'))

    def test_same_build_in_both_tags_is_unambiguous(self):
        self.assertEqual(self.query(stable=build())[0], build())

    def test_same_version_conflicting_identity_or_time_fails(self):
        for field, value in (('id', 11), ('completion_time', '2026-10-11 12:00:00')):
            stable = build()
            stable[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'Ambiguous'):
                self.query(stable=stable)

    def test_testing_pending_candidate_other_release_or_missing_tags_fail_before_query(self):
        for field, value in (('stableUpdateTag', 'f45-updates-testing'),
                             ('stableUpdateTag', 'f45-updates-pending'),
                             ('stableUpdateTag', 'f45-updates-candidate'),
                             ('stableUpdateTag', 'f44-updates'), ('kojiTag', 'f45-updates'),
                             ('kojiTag', 'f46'), ('fedora', True), ('stableUpdateTag', None)):
            policy = dict(POLICY, **{field: value})
            with self.subTest(field=field, value=value), patch.object(mod.urllib.request, 'urlopen') as fetch:
                with self.assertRaisesRegex(ValueError, 'exact reviewed'):
                    mod.latest(policy)
                fetch.assert_not_called()

    def test_either_query_error_fails_closed(self):
        for failure in (1, 2):
            with self.subTest(failure=failure), self.assertRaisesRegex(RuntimeError, 'Koji query failed'):
                self.query(failure=failure)

    def test_oversized_response_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'size limit'):
            self.query(raw=(b' ' * (mod.XML_LIMIT + 1),))

    def test_malformed_xml_fault_or_response_shape_is_rejected(self):
        data = [b'not XML', xmlrpc.client.dumps(xmlrpc.client.Fault(1, 'x' * 10000)).encode(),
                xmlrpc.client.dumps(([build()],), methodname='getLatestBuilds', allow_none=True).encode(),
                encoded([build()]).replace(b'</params>', b'<param><value><array><data></data></array></value></param></params>'),
                encoded({}), encoded([build(), build(identity=11)]), encoded(['not a build']),
                encoded([])]
        for raw in data:
            with self.subTest(raw=raw[:50]), self.assertRaises(ValueError):
                self.query(raw=(raw, encoded([])))

    def test_noncanonical_or_cross_fedora_build_fields_are_rejected(self):
        mutations = [('name', 'other'), ('version', '7.2.09'), ('version', '7.2.9+rc1'),
                     ('release', '301.fc44'), ('release', '0301.fc45'), ('release', '301.fc45.1'),
                     ('epoch', 1), ('epoch', False), ('id', True), ('nvr', 'wrong'),
                     ('completion_time', None), ('completion_time', 'not a timestamp')]
        for field, value in mutations:
            latest = build()
            latest[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.query(stable=latest)

    def test_newer_cross_series_build_is_selected_then_rejected_without_fallback(self):
        newer = build('7.3.0', '301.fc45', 11)
        selected, _ = self.query(stable=newer)
        self.assertEqual(selected, newer)
        current = {'release': '7.2.9-300.fc45.x86_64', 'packages': [{'name': n} for n in mod.PACKAGES]}
        with self.assertRaisesRegex(ValueError, 'approved series'):
            mod.candidate(POLICY, current, selected)

    def test_candidate_preserves_signed_provider_modules_and_downgrade_guard(self):
        current = {'release': '7.2.9-300.fc45.x86_64', 'packages': [{'name': n} for n in mod.PACKAGES],
                   'requiredModules': ['intel_ipu7', 'ipu_bridge']}
        selected, _ = self.query(stable=build(release='301.fc45', identity=11))
        proposed = mod.candidate(POLICY, current, selected)
        self.assertEqual(proposed['baseUrl'],
                         'https://kojipkgs.fedoraproject.org/packages/kernel/7.2.9/301.fc45/data/signed/f577861e/x86_64')
        self.assertEqual(proposed['requiredModules'], current['requiredModules'])
        self.assertEqual([p['name'] for p in proposed['packages']], mod.PACKAGES)
        self.assertEqual(POLICY['maxLagDays'], 7)
        with self.assertRaisesRegex(ValueError, 'downgrade'):
            mod.candidate(POLICY, current, build(release='299.fc45'))


if __name__ == '__main__':
    unittest.main()
