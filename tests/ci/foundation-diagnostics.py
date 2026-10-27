#!/usr/bin/env python3
"""Versioned diagnostic consumers retain legacy and partial observations."""
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import foundation_timings as timings
SPEC = importlib.util.spec_from_file_location('guest_timings', ROOT / 'scripts/bluebuild/guest-timings.py')
guest = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(guest)


def record(stage='nix-activities'):
    return {'schema': 2, 'kind': 'foundation-stage-timing', 'authorizesPublication': False,
            'stage': stage, 'startedAt': '2026-10-27T12:00:00Z', 'seconds': 0,
            'outcome': 'success', 'status': 0, 'details': {
                'logger': 'nix-internal-json-v1', 'evaluation': 'unknown', 'builds': 2, 'substitutions': 3,
                'buildSeconds': 10., 'substitutionSeconds': 8., 'overlapSeconds': 5.,
                'incomplete': False, 'rejectedRecords': 0}}


class Diagnostics(unittest.TestCase):
    def test_v2_and_legacy_partial_rows_survive_same_envelope(self):
        legacy = record('activation'); legacy['schema'] = 1; del legacy['details']
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'receipt.json'
            guest.collect(io.StringIO(''.join('FOUNDATION_TIMING ' + json.dumps(row) + '\n'
                                             for row in (legacy, record()))), output, console=io.StringIO())
            value = json.loads(output.read_text())
            self.assertEqual(value['foundation']['stages'], [legacy, record()])
            self.assertLess(output.stat().st_size, 16384)

    def test_malformed_versions_fields_and_overlap_are_rejected(self):
        for change in (lambda v: v.update(schema=True), lambda v: v.update(schema=3),
                       lambda v: v['details'].update(rawArguments='private'),
                       lambda v: v['details'].update(overlapSeconds=11),
                       lambda v: v['details'].update(builds=True),
                       lambda v: v['details'].update(buildSeconds=float('nan')),
                       lambda v: v['details'].update(incomplete=True)):
            value = record(); change(value)
            with self.assertRaises(ValueError): timings.validate(value)

    def test_unknown_intervals_and_separate_resource_scope(self):
        value = record(); value['details'].update(incomplete=True, buildSeconds=None,
                                                 substitutionSeconds=None, overlapSeconds=None)
        timings.validate(value)
        value = record('resource-nix-daemon')
        value['details'] = {'scope': 'shared-daemon', 'memoryCurrentBytes': None,
                            'memoryPeakBytes': None, 'cpuUsageUsec': None, 'available': False}
        timings.validate(value)
        value['details']['scope'] = 'client'
        with self.assertRaises(ValueError): timings.validate(value)

    def test_duplicate_unknown_and_oversize_lines_do_not_discard_valid_rows(self):
        lines = ['FOUNDATION_TIMING ' + json.dumps(record()) + '\n'] * 2
        lines += ['FOUNDATION_TIMING ' + 'x' * 5000 + '\n']
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'receipt.json'
            guest.collect(io.StringIO(''.join(lines)), output, console=io.StringIO())
            value = json.loads(output.read_text())['foundation']
            self.assertEqual(len(value['stages']), 1)
            self.assertEqual(value['rejectedRecords'], 2)


if __name__ == '__main__': unittest.main()
