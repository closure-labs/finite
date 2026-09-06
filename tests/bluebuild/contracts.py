#!/usr/bin/env python3
"""Contracts for independent images and the trusted publication boundary."""
from pathlib import Path
import json
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    'bluefin-generic': ('bluefin', 'generic-x86_64', ['bluefin-generic', 'latest']),
    'bluefin-next': ('bluefin', 'next-x86_64', ['next']),
    'bluefin-dx-generic': ('bluefin-dx', 'generic-x86_64', ['bluefin-dx-generic']),
    'bluefin-dx-next': ('bluefin-dx', 'next-x86_64', ['dev-next']),
}

def read(path):
    return yaml.safe_load((ROOT / path).read_text())

def modules(recipe, seen=()):
    for module in recipe['modules']:
        if 'from-file' in module:
            path = module['from-file']
            if path in seen:
                raise ValueError('Cyclic recipe import')
            yield from modules(read('recipes/' + path), (*seen, path))
        else:
            yield module

class BlueBuildContracts(unittest.TestCase):
    def test_profiles_are_independent_and_tags_do_not_overlap(self):
        tags = []
        for profile, (foundation, hardware, expected_tags) in EXPECTED.items():
            recipe = read('recipes/' + profile + '.yml')
            self.assertEqual(recipe['version'], 1)
            self.assertEqual(recipe['name'], 'finite')
            self.assertEqual(recipe['base-image'], 'ghcr.io/ublue-os/' + foundation)
            self.assertEqual(recipe['image-version'], 'stable')
            self.assertEqual(recipe['alt-tags'], expected_tags)
            self.assertEqual(recipe['labels']['io.finite.hardware'], hardware)
            tags.extend(recipe['alt-tags'])
            expanded = list(modules(recipe))
            self.assertTrue(all('@v' in m['type'] for m in expanded))
            scripts = [s for m in expanded for s in m.get('scripts', [])]
            self.assertEqual('kernel-next.sh' in scripts, hardware == 'next-x86_64')
            for script in scripts:
                self.assertTrue((ROOT / 'files/scripts' / script).is_file())
            kinds = [m['type'].split('@')[0] for m in expanded]
            self.assertLess(kinds.index('dnf'), kinds.index('files'))
            self.assertLess(kinds.index('signing'), len(kinds)-1)
        self.assertEqual(len(tags), len(set(tags)))

    def test_publication_is_guarded_and_gate_includes_failures(self):
        workflow = read('.github/workflows/build.yml')
        images = workflow['jobs']['images']
        self.assertFalse(images['strategy']['fail-fast'])
        self.assertEqual({p['profile'] for p in images['strategy']['matrix']['include']}, set(EXPECTED))
        self.assertEqual(images['permissions']['packages'], 'read')
        self.assertNotIn('secrets', images)
        self.assertFalse(images['with']['publish'])
        publish = workflow['jobs']['publish']
        trust = publish['if']
        for required in ['closure-labs/finite', "github.ref == 'refs/heads/main'", "github.event_name == 'push'"]:
            self.assertIn(required, trust)
            self.assertIn(required, images['if'])
        self.assertEqual(publish['strategy'], images['strategy'])
        self.assertTrue(publish['with']['publish'])
        self.assertEqual(publish['permissions']['packages'], 'write')
        reusable = read('.github/workflows/image.yml')
        build = reusable['jobs']['build']
        self.assertNotIn('permissions', build)  # inherits the caller's token scope
        action = next(s for s in build['steps'] if s.get('uses', '').startswith('blue-build/'))
        self.assertEqual(action['uses'], 'blue-build/github-action@836161eb076426a451e6a0054f722b1153b8b3ad')
        self.assertEqual(action['with']['cli_version'], 'v0.9.37')
        self.assertEqual(action['with']['push'], '${{ inputs.publish }}')
        self.assertEqual(action['with']['registry_token'], '${{ github.token }}')
        secret = action['with']['cosign_private_key']
        self.assertIn('inputs.publish', secret)
        self.assertNotIn('env.', secret)
        self.assertIn("|| ''", secret)
        for key in ['rechunk', 'chunkah', 'build_chunked_oci']:
            self.assertFalse(action['with'][key])
        gate = workflow['jobs']['gate']
        self.assertEqual(gate['name'], 'CI gate')
        self.assertEqual(gate['if'], 'always()')
        self.assertEqual(set(gate['needs']), {'checks', 'images', 'publish'})

    def test_runtime_catalog_has_no_build_graph(self):
        source = (ROOT / 'lib/image-payload.nix').read_text()
        for legacy in ['eval-profile-graph', 'render-profile-artifacts', 'image-matrix', 'Containerfile']:
            self.assertNotIn(legacy, source)
        lock = json.loads((ROOT / 'sources/kernel-next.json').read_text())
        for package in lock['packages']:
            self.assertRegex(package['sha256'], r'^[0-9a-f]{64}$')
        self.assertEqual(len(lock['packages']), 5)

if __name__ == '__main__':
    unittest.main()
