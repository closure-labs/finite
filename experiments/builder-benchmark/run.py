#!/usr/bin/env python3
"""Paired local-output builds on one hosted runner; never publish or sign."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
BASE = '49efd91b3ddaa775469b45d94c2e2424df3fa034'
BUILDKIT = 'moby/buildkit@sha256:cec9f139f45e93c5c69c60f8b07cfad9f43f4ef6b6a6cd917527fea5ff2e3dea'
SPEC = importlib.util.spec_from_file_location('containerfile', ROOT / 'experiments/containerfile/prepare.py')
containerfile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(containerfile)
TIMING_SPEC = importlib.util.spec_from_file_location('stage_measure', ROOT / 'scripts/bluebuild/measure.py')
timing = importlib.util.module_from_spec(TIMING_SPEC)
TIMING_SPEC.loader.exec_module(timing)
OUT = ROOT / '.bluebuild/benchmark'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def command(args, directory=None, env=None, log=None):
    print('+ ' + ' '.join(map(str, args)), flush=True)
    if log:
        with log.open('w') as output:
            subprocess.run(args, cwd=directory or ROOT, env=env, stdout=output,
                           stderr=subprocess.STDOUT, check=True)
    else:
        subprocess.run(args, cwd=directory or ROOT, env=env, check=True)


def measure(directory, name, args, **kwargs):
    start = time.monotonic()
    stamp = datetime.now(timezone.utc).isoformat()
    network = timing.network_bytes()
    status = 1
    try:
        command(args, **kwargs)
        status = 0
    finally:
        with (directory / 'timings.jsonl').open('a') as output:
            output.write(json.dumps({'stage': name, 'startedAt': stamp,
                'seconds': round(time.monotonic() - start, 3), 'status': status,
                'runnerNetworkDelta': {key: max(0, value - network[key])
                    for key, value in timing.network_bytes().items() if key in network}}) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def graph(path):
    # Keep every raw event alongside this projection. Durations can overlap;
    # vertex totals are deliberately not added into wall-clock stage totals.
    vertices = {}
    for line in path.read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get('id') and event.get('name'):
            previous = vertices.setdefault(event['id'], {})
            previous.update(event)
    return {'cachedVertices': sum(bool(v.get('cached')) for v in vertices.values()),
            'vertices': list(vertices.values()), 'durationsOverlap': True}


def build_command(builder, dockerfile, context, tag, metadata, output, args):
    # Identical frontend, platform, pull and exporter flags. No registry/GHA
    # cache imports/exports, secrets, SSH forwarding, push or signing.
    result = ['docker', 'buildx', 'build', '--builder', builder, '--platform', 'linux/amd64',
              '--pull', '--progress=rawjson', '--provenance=false', '--file', str(dockerfile),
              '--tag', tag, '--metadata-file', str(metadata), '--output', output]
    for key, value in args.items():
        result += ['--build-arg', key + '=' + value]
    return result + [str(context)]


def verify(directory, image, plan):
    info = json.loads(subprocess.check_output(['docker', 'image', 'inspect', image], text=True))[0]
    labels = info.get('Config', {}).get('Labels', {})
    for key, value in {'io.finite.profile': plan['profile'],
                       'org.opencontainers.image.revision': plan['sourceRevision'],
                       'org.opencontainers.image.base.digest': plan['baseDigest'],
                       'io.finite.production-eligible': 'false',
                       'io.finite.reference-build-inputs': plan['referenceIdentity']}.items():
        if labels.get(key) != value:
            raise ValueError('Image does not match benchmark inputs: ' + key)
    write(directory / 'image.json', info)
    measure(directory, 'runtime-verification', ['docker', 'run', '--rm', '--network=none',
        '--entrypoint', 'bash', '-v', str(ROOT / 'scripts/bluebuild/verify-image.sh') + ':/verify.sh:ro',
        image, '/verify.sh', plan['profile']])
    inventory = subprocess.check_output(['docker', 'run', '--rm', '--network=none', '--entrypoint',
        'rpm', image, '-qa', '--qf', '%{NAME}\t%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\n'], text=True)
    packages, packages_sha = containerfile.rpm_inventory(inventory)
    observed = json.loads(subprocess.check_output(['docker', 'run', '--rm', '--network=none',
        '--entrypoint', 'python3', image, '-c', containerfile.PROVENANCE_QUERY], text=True))
    provenance = containerfile.validate_provenance(observed, plan['foundationSource'], packages)
    write(directory / 'runtime.json', {'imageId': image, 'sourceRevision': plan['sourceRevision'],
        'referenceIdentity': plan['referenceIdentity'], 'profile': plan['profile'],
        'packages': packages, 'packagesSha256': packages_sha, 'provenance': provenance,
        'authorizesPublication': False})


def context(directory, plan, method):
    directory.mkdir()
    shutil.copytree(ROOT / 'files', directory / 'files', symlinks=True)
    shutil.copy(ROOT / 'cosign.pub', directory / 'cosign.pub')
    if method == 'bluebuild':
        for scripts in ROOT.glob('.bluebuild-scripts_*'):
            shutil.copytree(scripts, directory / scripts.name)
        shutil.copy(OUT / 'bluebuild.Containerfile', directory / 'Containerfile')
        return {}
    shutil.copytree(ROOT / 'experiments/containerfile', directory / 'experiments/containerfile',
                    ignore=shutil.ignore_patterns('__pycache__'))
    target = directory / 'scripts/bluebuild'; target.mkdir(parents=True)
    shutil.copy(ROOT / 'scripts/bluebuild/verify-image.sh', target / 'verify-image.sh')
    write(directory / '.bluebuild/containerfile/plan.json', plan)
    shutil.copy(ROOT / 'experiments/containerfile/Containerfile', directory / 'Containerfile')
    return {'BASE_IMAGE': plan['baseImage'] + '@' + plan['baseDigest'],
        'COSIGN_IMAGE': plan['cosignImage'], 'BLUEBUILD_IMAGE': plan['bluebuildImage'],
        'PROFILE': plan['profile'], 'FOUNDATION': plan['foundation'],
        'SOURCE_REVISION': plan['sourceRevision'], 'BASE_DIGEST': plan['baseDigest'],
        'REFERENCE_IDENTITY': plan['referenceIdentity'], 'EXPERIMENT_IDENTITY': plan['experimentIdentity'],
        'CREATED': plan['created'], 'VERSION': plan['version'],
        'DESCRIPTION': plan['description'], 'URL': plan['url']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True, choices=containerfile.PROFILES)
    parser.add_argument('--repetition', required=True, type=int, choices=(1, 2))
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_EVENT_NAME') != 'pull_request':
        raise ValueError('Authorized internal hosted PR only')
    revision = containerfile.authorized_revision()
    if subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() != revision:
        raise ValueError('Checkout differs from authorized head')
    # The base snapshot is part of the plan, never a moving main checkout.
    command(['git', 'merge-base', '--is-ancestor', BASE, revision])
    immutable = ['recipes', 'sources', 'flake.lock', 'files', 'lib/ci-payload.nix',
                 'scripts/bluebuild', 'lib/image-payload.nix', 'scripts/ci/image_identity.py']
    command(['git', 'diff', '--exit-code', BASE, revision, '--', *immutable])
    OUT.mkdir(parents=True, exist_ok=False)
    plan = containerfile.prepare(args.profile)
    order = ['bluebuild', 'containerfile'] if args.repetition == 1 else ['containerfile', 'bluebuild']
    write(OUT / 'plan.json', {'schema': 1, 'sourceRevision': revision, 'baseline': BASE,
        'runId': os.environ['GITHUB_RUN_ID'], 'attempt': os.environ['GITHUB_RUN_ATTEMPT'],
        'profile': args.profile, 'repetition': args.repetition, 'order': order,
        'buildkit': BUILDKIT,
        'conditions': ['empty-private-builder', 'same-builder-unchanged-inputs'],
        'vmConditions': ['cold-output-only'], 'authorizesPublication': False, 'inputs': plan})
    resources = subprocess.check_output(['python3', '-c',
        "import sys;sys.path.insert(0,'scripts/ci');import importlib; m=importlib.import_module('nix-resources');print(m.detect())"], text=True)
    write(OUT / 'host.json', {'resources': resources.strip(),
        'cpu': subprocess.check_output(['lscpu', '-J'], text=True),
        'kernel': os.uname().release, 'runner': {k: os.environ.get(k) for k in
            ('RUNNER_NAME', 'RUNNER_OS', 'RUNNER_ARCH', 'ImageOS', 'ImageVersion', 'RUNNER_ENVIRONMENT')},
        'disk': shutil.disk_usage(ROOT)._asdict()})
    measure(OUT, 'payload-staging', ['bash', 'scripts/bluebuild/stage.sh', args.profile])
    # Generate once: timestamps/build UUID and all payload bytes remain stable
    # through cold and warm solves. Use the pinned CLI's embedded module scripts.
    measure(OUT, 'bluebuild-generation', ['bluebuild', 'generate', '--build-driver', 'docker',
        '--run-driver', 'docker', '--registry', 'ghcr.io', '--registry-namespace', 'closure-labs',
        '-o', str(OUT / 'bluebuild.Containerfile'), 'recipes/' + args.profile + '.yml'])
    generated_path = OUT / 'bluebuild.Containerfile'
    cli = json.loads((ROOT / 'sources/bluebuild-cli.json').read_text())
    generated_text = generated_path.read_text()
    cli_tag = cli['image'] + ':' + cli['version']
    if cli_tag not in generated_text:
        raise ValueError('Generated BlueBuild runtime CLI reference changed')
    generated_path.write_text(generated_text.replace(cli_tag, cli['image'] + '@' + cli['digest']))
    with (OUT / 'bluebuild.Containerfile').open('a') as generated:
        generated.write('\nLABEL io.finite.production-eligible="false" '
            f'io.finite.build-inputs="benchmark:{revision}" '
            f'io.finite.reference-build-inputs="{plan["referenceIdentity"]}" '
            f'org.opencontainers.image.revision="{revision}"\n')
    env = dict(os.environ, GITHUB_SHA=revision, SOURCE_REVISION=revision, PROFILE=args.profile,
               BUILD_IDENTITY='benchmark:' + revision)
    env.pop('SOURCE_DATE_EPOCH', None)
    with tempfile.TemporaryDirectory(prefix='finite-matched-') as work:
        for method in order:
            root = OUT / method; root.mkdir()
            ctx = Path(work) / method
            build_args = context(ctx, plan, method)
            write(root / 'context-files.json', {str(p.relative_to(ctx)): digest(p)
                for p in sorted(ctx.rglob('*')) if p.is_file()})
            builder = 'matched-' + method
            # Each method starts with its own empty state, on this exact host.
            command(['docker', 'buildx', 'create', '--name', builder, '--driver', 'docker-container',
                     '--driver-opt', 'image=' + BUILDKIT])
            try:
                measure(root, 'builder-bootstrap', ['docker', 'buildx', 'inspect', '--builder', builder, '--bootstrap'])
                command(['docker', 'buildx', 'du', '--builder', builder], log=root / 'initial-cache.txt')
                for temperature in ('cold', 'warm'):
                    trial = root / temperature; trial.mkdir()
                    tag = 'localhost/finite-matched:' + method
                    common = (builder, ctx / 'Containerfile', ctx, tag)
                    measure(trial, 'assembly', build_command(*common, trial / 'assembly-metadata.json',
                        'type=cacheonly', build_args), env=env, log=trial / 'assembly-progress.jsonl')
                    archive = Path(work) / 'image.tar'
                    measure(trial, 'docker-archive-export', build_command(*common, trial / 'export-metadata.json',
                        'type=docker,dest=' + str(archive), build_args), env=env, log=trial / 'export-progress.jsonl')
                    for phase in ('assembly', 'export'):
                        write(trial / (phase + '-graph.json'), graph(trial / (phase + '-progress.jsonl')))
                    measure(trial, 'docker-load', ['docker', 'load', '--input', str(archive)])
                    archive.unlink()
                    image = subprocess.check_output(['docker', 'inspect', '--format', '{{.Id}}', tag], text=True).strip()
                    if not containerfile.DIGEST.fullmatch(image):
                        raise ValueError('Immutable Docker image ID required')
                    verify(trial, image, plan)
                    if temperature == 'cold':
                        (ROOT / '.bluebuild' / (args.profile + '-image-ref.txt')).write_text(image + '\n')
                        measure(trial, 'fresh-vm-wrapper', ['bash', 'scripts/bluebuild/local-vm.sh', args.profile], env=env)
                        shutil.copytree(ROOT / '.bluebuild/vm-local', trial / 'vm-local')
                        shutil.rmtree(ROOT / '.bluebuild/vm-local')
                        timings = ROOT / '.bluebuild' / (args.profile + '-timings.jsonl')
                        if timings.exists():
                            shutil.copy(timings, trial / 'vm-timings.jsonl'); timings.unlink()
                    # Remove daemon layers before every load, including warm.
                    ids = subprocess.check_output(['docker', 'image', 'ls', '--quiet', '--no-trunc',
                        '--filter', 'label=io.finite.profile=' + args.profile], text=True).split()
                    if ids:
                        command(['docker', 'image', 'rm', '--force', *sorted(set(ids))])
                    command(['docker', 'buildx', 'du', '--builder', builder], log=trial / 'cache-after.txt')
            finally:
                command(['docker', 'buildx', 'rm', builder])
    runtimes = {method: {temperature: json.loads((OUT / method / temperature / 'runtime.json').read_text())
                for temperature in ('cold', 'warm')} for method in order}
    inventories = {method: {tuple(sorted(package.items())) for package in runtimes[method]['cold']['packages']}
                   for method in order}
    write(OUT / 'comparison.json', {'sourceRevision': revision, 'profile': args.profile,
        'referenceIdentity': plan['referenceIdentity'], 'authorizesPublication': False,
        'warmInventoryStable': {method: runtimes[method]['cold']['packagesSha256'] ==
            runtimes[method]['warm']['packagesSha256'] for method in order},
        'onlyBlueBuild': [dict(p) for p in sorted(inventories['bluebuild'] - inventories['containerfile'])],
        'onlyContainerfile': [dict(p) for p in sorted(inventories['containerfile'] - inventories['bluebuild'])]})


if __name__ == '__main__':
    main()
