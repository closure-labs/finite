"""Offline metadata fixtures; no Nix commands, builds, store access or network."""
import copy
import json
from pathlib import Path
import unittest

from validate import derivation_source


DRV = '/nix/store/' + 'a' * 32 + '-determinate-nix-store-3.24.1.drv'
SRC = '/nix/store/' + 'b' * 32 + '-source'
OTHER = '/nix/store/' + 'c' * 32 + '-source'


def modern(env=None, **attrs):
    return {'version': 4, 'derivations': {Path(DRV).name: {
        'env': {'src': SRC} if env is None else env, **attrs}}}


class Metadata(unittest.TestCase):
    def accept(self, value):
        self.assertEqual(derivation_source(json.dumps(value), DRV), Path(SRC))

    def reject(self, value):
        with self.assertRaises((AssertionError, ValueError, TypeError)):
            derivation_source(json.dumps(value), DRV)

    def test_pinned_v4(self):
        self.accept(modern())

    def test_legacy(self):
        self.accept({DRV: {'env': {'src': SRC}}})

    def test_structured_attrs(self):
        self.accept(modern({}, structuredAttrs={'src': SRC}))

    def test_legacy_structured_json(self):
        self.accept({DRV: {'env': {'__json': json.dumps({'src': SRC})}}})

    def test_consistent_multiple_sources(self):
        self.accept(modern({'src': SRC, '__json': json.dumps({'src': SRC})},
                           structuredAttrs={'src': SRC}))

    def test_unknown_version(self):
        v = modern(); v['version'] = 5; self.reject(v)

    def test_bool_version(self):
        v = modern(); v['version'] = True; self.reject(v)

    def test_extra_envelope_field(self):
        v = modern(); v['other'] = {}; self.reject(v)

    def test_missing_derivations(self):
        self.reject({'version': 4})

    def test_wrong_deriver(self):
        self.reject({'version': 4, 'derivations': {'wrong.drv': {'env': {'src': SRC}}}})

    def test_multiple_derivations(self):
        v = modern(); v['derivations']['wrong.drv'] = copy.deepcopy(next(iter(v['derivations'].values())))
        self.reject(v)

    def test_empty_derivations(self):
        self.reject({'version': 4, 'derivations': {}})

    def test_non_object(self):
        self.reject([])

    def test_missing_source(self):
        self.reject(modern({}))

    def test_bad_source_paths(self):
        for src in (None, [], 42, '/tmp/source', SRC + '/child', SRC + '/../other'):
            with self.subTest(source=src):
                self.reject(modern({'src': src}))

    def test_conflicting_structured_source(self):
        self.reject(modern(structuredAttrs={'src': OTHER}))

    def test_conflicting_legacy_source(self):
        self.reject(modern({'src': SRC, '__json': json.dumps({'src': OTHER})}))

    def test_malformed_structured_metadata(self):
        self.reject(modern(structuredAttrs=[]))
        self.reject(modern({'__json': '[]'}))
        self.reject(modern({'__json': '{'}))

    def test_duplicate_json_keys(self):
        raw = json.dumps(modern()).replace('"version": 4', '"version": 4, "version": 4')
        with self.assertRaises(ValueError):
            derivation_source(raw, DRV)
        with self.assertRaises(ValueError):
            derivation_source(json.dumps(modern({'__json': '{"src":"x","src":"y"}'})), DRV)


if __name__ == '__main__':
    unittest.main()
