#!/usr/bin/env python3
"""Contracts for independent images and the trusted publication boundary."""
from pathlib import Path
import json
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    'finite': ('bluefin', 'generic-x86_64', ['finite', 'latest']),
    'finite-dev': ('bluefin-dx', 'generic-x86_64', ['finite-dev']),
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
    def test_obsolete_publication_stops_before_expensive_setup_without_gating_prs(self):
        image = read('.github/workflows/image.yml')['jobs']['build']['steps']
        security = read('.github/workflows/publication.yml')['jobs']['security']['steps']
        for steps, name, expensive in (
                (image, 'Stop obsolete publication before image setup', 'Make room for the image build'),
                (security, 'Stop obsolete publication before security setup', 'Reuse authenticated publisher evidence from this build')):
            index = next(i for i, step in enumerate(steps) if step.get('name') == name)
            self.assertEqual(steps[index - 1]['uses'], '$/.github/actions/setup-nix')
            self.assertEqual(steps[index]['run'], 'python3 scripts/bluebuild/qualification-preflight.py --revision "$GITHUB_SHA"')
            self.assertNotIn('continue-on-error', steps[index])
            self.assertEqual(steps[index]['env']['GH_TOKEN'], '${{ github.token }}')
            self.assertLess(index, next(i for i, step in enumerate(steps) if step.get('name') == expensive))
        self.assertEqual(next(step for step in image if step.get('name', '').startswith('Stop obsolete'))['if'], 'inputs.publish')
        for steps, name, expensive in (
                (image, 'Recheck publication after image preparation', 'Build with BlueBuild'),
                (security, 'Recheck publication before inventory and scanning', 'Make room for the immutable image inventory')):
            index = next(i for i, step in enumerate(steps) if step.get('name') == name)
            self.assertEqual(steps[index]['run'], 'python3 scripts/bluebuild/qualification-preflight.py --revision "$GITHUB_SHA"')
            self.assertEqual(steps[index + 1]['name'], expensive)
        checks = read('.github/workflows/build.yml')['jobs']['checks']['steps']
        retain = checks[-1]
        self.assertEqual(retain['if'], 'always()')
        self.assertIn('source-checks-${{ github.run_id }}-${{ github.run_attempt }}', retain['with']['name'])
        self.assertEqual(retain['with']['retention-days'], 14)

    def test_profiles_are_independent_and_tags_do_not_overlap(self):
        tags = []
        for profile, (foundation, hardware, expected_tags) in EXPECTED.items():
            recipe = read('recipes/' + profile + '.yml')
            self.assertEqual(recipe['version'], 1)
            self.assertEqual(recipe['name'], 'finite')
            self.assertEqual(recipe['labels']['io.finite.profile'], profile)
            self.assertEqual(recipe['blue-build-tag'], json.loads((ROOT / 'sources/bluebuild-cli.json').read_text())['version'])
            self.assertEqual(recipe['base-image'], 'ghcr.io/ublue-os/' + foundation)
            self.assertRegex(recipe['image-version'], r'^stable@sha256:[0-9a-f]{64}$')
            self.assertEqual(recipe['alt-tags'], expected_tags)
            self.assertEqual(recipe['labels']['io.finite.hardware'], hardware)
            tags.extend(recipe['alt-tags'])
            expanded = list(modules(recipe))
            self.assertTrue(all('@v' in m['type'] for m in expanded))
            scripts = [s for m in expanded for s in m.get('scripts', [])]
            self.assertNotIn('kernel-next.sh', scripts)
            for script in scripts:
                self.assertTrue((ROOT / 'files/scripts' / script).is_file())
            kinds = [m['type'].split('@')[0] for m in expanded]
            snapshot_step = next(i for i, m in enumerate(expanded)
                                 if any('check-upstream-kernel snapshot' in snippet for snippet in m.get('snippets', [])))
            verify_step = next(i for i, m in enumerate(expanded)
                               if any('check-upstream-kernel verify' in snippet for snippet in m.get('snippets', [])))
            finalize_step = next(i for i, m in enumerate(expanded)
                                 if 'finalize.sh' in m.get('scripts', []))
            self.assertEqual(kinds.count('initramfs'), 1)
            self.assertLess(snapshot_step, kinds.index('dnf'))
            self.assertLess(kinds.index('initramfs'), verify_step)
            self.assertLess(verify_step, finalize_step)
            self.assertLess(kinds.index('initramfs'), finalize_step)
            self.assertLess(kinds.index('dnf'), kinds.index('files'))
            self.assertLess(kinds.index('signing'), len(kinds)-1)
        self.assertEqual(len(tags), len(set(tags)))

    def test_publication_is_guarded_and_gate_includes_failures(self):
        workflow = read('.github/workflows/build.yml')
        images = workflow['jobs']['images']
        self.assertFalse(images['strategy']['fail-fast'])
        self.assertIn('needs.checks.outputs.matrix', images['strategy']['matrix'])
        self.assertEqual(images['permissions']['packages'], 'read')
        self.assertNotIn('secrets', images)
        self.assertFalse(images['with']['publish'])
        publish = workflow['jobs']['publish']
        trust = publish['if']
        for required in ['closure-labs/finite', "github.ref == 'refs/heads/main'", "github.event_name == 'push'"]:
            self.assertIn(required, trust)
            self.assertIn(required, images['if'])
        self.assertEqual(publish['strategy'], images['strategy'])
        self.assertEqual(publish['uses'], '$/.github/workflows/publication.yml')
        self.assertEqual(publish['permissions']['packages'], 'write')
        reusable = read('.github/workflows/image.yml')
        build = reusable['jobs']['build']
        self.assertNotIn('permissions', build)  # inherits the caller's token scope
        steps = build['steps']
        self.assertFalse(any(s.get('uses', '').startswith('blue-build/') for s in steps))
        action = next(s for s in steps if s.get('name') == 'Build with BlueBuild')
        self.assertNotIn('nix develop', action['run'])
        tools = next(step for step in reusable['jobs']['build']['steps']
                     if 'image-tools --no-link' in step.get('run', ''))
        self.assertIn('echo "$tools/bin" >>"$GITHUB_PATH"', tools['run'])
        self.assertIn('scripts/bluebuild/build.sh "$PROFILE" "$PUBLISH"', action['run'])
        self.assertEqual(action['env']['PUBLISH'], '${{ inputs.publish }}')
        self.assertEqual(action['env']['BB_PASSWORD'], '${{ github.token }}')
        self.assertNotIn('COSIGN_PRIVATE_KEY', action['env'])
        self.assertEqual(publish['secrets'], {'COSIGN_PRIVATE_KEY': '${{ secrets.COSIGN_PRIVATE_KEY }}',
                                             'COSIGN_PASSWORD': '${{ secrets.COSIGN_PASSWORD }}',
                                             'DECIDER_KEY': '${{ secrets.DECIDER_KEY }}',
                                             'DECIDER_CLIENT': '${{ secrets.DECIDER_CLIENT }}'})
        builder = next(s for s in steps if s.get('uses', '').startswith('docker/setup-buildx-action@'))
        self.assertEqual(builder['with']['name'], 'bluebuild')
        self.assertEqual(builder['with']['driver-opts'], 'default-load=true')
        names = [s.get('name', '') for s in steps]
        self.assertLess(names.index('Prepare candidate publication'), names.index('Build with BlueBuild'))
        self.assertLess(names.index('Install the verified locked BlueBuild CLI'), names.index('Build with BlueBuild'))
        self.assertIn('Verify assembled image', names)
        publication = read('.github/workflows/publication.yml')
        self.assertNotIn('secrets', publication['jobs']['build'])
        self.assertNotIn('secrets', publication['jobs']['qualification'])
        promotion = publication['jobs']['promote']
        self.assertEqual(promotion['needs'], ['build', 'security', 'sign', 'qualification'])
        self.assertIn("needs.build.result == 'success'", promotion['if'])
        self.assertIn('!cancelled()', promotion['if'])
        self.assertEqual(publication['jobs']['qualification']['needs'], ['build', 'sign'])
        self.assertNotIn('preflight', publication['jobs'])
        qualification = read('.github/workflows/qualification.yml')
        preparation = qualification['jobs']['prepare']['steps']
        preflight = next(s for s in preparation
                         if s.get('name') == 'Reject obsolete publication before reuse or VM work')
        self.assertEqual(preflight['if'], '${{ !inputs.validation_only }}')
        self.assertIn('publication-current.py', preflight['run'])
        self.assertIn('--record', preflight['run'])
        self.assertLess(preparation.index(preflight),
                        next(i for i, s in enumerate(preparation) if s.get('id') == 'reuse'))
        self.assertEqual(publication['jobs']['qualification']['with']['build_evidence'],
                         '${{ needs.build.outputs.evidence }}')
        acceptance = next(s for s in qualification['jobs']['phase']['steps']
                          if s.get('id') == 'acceptance')
        self.assertNotIn('continue-on-error', acceptance)
        self.assertEqual(qualification['jobs']['phase']['needs'], 'prepare')
        self.assertEqual(qualification['jobs']['phase']['strategy']['fail-fast'],
                         "${{ inputs.validation_only && inputs.installer_benchmark != '' }}")
        inputs = qualification.get('on', qualification.get(True))['workflow_call']['inputs']
        self.assertIs(inputs['validation_only']['default'], False)
        self.assertEqual(inputs['installer_benchmark']['default'], '')
        production = publication['jobs']['qualification']['with']
        self.assertIs(production.get('validation_only', False), False)
        self.assertEqual(production.get('installer_benchmark', ''), '')
        self.assertEqual(qualification['jobs']['functional']['needs'], ['prepare', 'phase'])
        self.assertIn("needs.phase.result == 'success'", qualification['jobs']['functional']['if'])
        self.assertIn("needs.prepare.outputs.reused == 'true'", qualification['jobs']['functional']['if'])
        self.assertEqual(promotion['env']['FINITE_QUALIFICATION_MODE'], 'enforce')
        self.assertEqual(build['env']['FINITE_QUALIFICATION_MODE'], 'enforce')
        gate = workflow['jobs']['gate']
        self.assertEqual(gate['name'], 'CI gate')
        self.assertEqual(gate['if'], 'always()')
        self.assertEqual(set(gate['needs']), {'impact', 'docs', 'checks', 'images', 'publish', 'repository-secrets'})

    def test_upstream_recovery_and_health_are_independent_of_update_prs(self):
        workflow = read('.github/workflows/update-bluefin.yml')
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        check, update, recover = (workflow['jobs'][key] for key in ('check', 'update', 'recover'))
        self.assertEqual(check['name'], 'Resolve Bluefin upstream')
        self.assertEqual(update['needs'], 'check')
        self.assertNotIn('needs', recover)
        self.assertEqual(recover['permissions'], {'contents': 'read', 'actions': 'write'})
        for job in (check, recover):
            self.assertIn("github.ref == 'refs/heads/main'", job['if'])
            self.assertIn("github.repository == 'closure-labs/finite'", job['if'])
        pr = next(step for step in update['steps'] if step.get('uses', '').startswith('peter-evans/'))
        self.assertEqual(pr['with']['branch'], 'automation/update-bluefin')
        self.assertEqual(pr['with']['add-paths'], 'recipes/finite*.yml')
        health = read('.github/workflows/upstream-health.yml')
        self.assertEqual(health['permissions'], {'contents': 'read', 'actions': 'read'})

    def test_runtime_catalog_has_no_build_graph(self):
        source = (ROOT / 'lib/image-payload.nix').read_text()
        for legacy in ['eval-profile-graph', 'render-profile-artifacts', 'image-matrix', 'Containerfile']:
            self.assertNotIn(legacy, source)
        self.assertNotIn('kernel-next', source)
        self.assertNotIn('image-payload-next', (ROOT / 'modules/outputs.nix').read_text())

if __name__ == '__main__':
    unittest.main()
