#!/usr/bin/env python3
"""VM diagnostic: seal against canonical OCI metadata, then verify it remains stable."""

import argparse
import json
import os
import platform
from pathlib import Path
import re
import subprocess
import tomllib


ROOT = Path(__file__).resolve().parents[2]


def run(args, **kwargs):
    print('+', ' '.join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def capture(args):
    return subprocess.check_output(list(map(str, args)), text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--image', required=True)
    parser.add_argument('--output-image', required=True)
    parser.add_argument('--archive-name', choices=['base', 'update'], required=True)
    args = parser.parse_args()
    state = args.state.resolve()
    if not state.is_relative_to(ROOT / 'artifacts'):
        raise SystemExit('State must be under this checkout\'s artifacts directory')
    for image in [args.image, args.output_image]:
        if not re.fullmatch(r'localhost/[a-z0-9][a-z0-9/_.:-]*', image):
            raise SystemExit('Only explicit localhost test-image tags are supported')
    name = args.archive_name
    work = state / f'canonical-{name}'
    work.mkdir(mode=0o700, exist_ok=True)
    if (work / 'result.json').exists():
        raise SystemExit('This diagnostic already completed; use a fresh state directory')
    image_id = capture(['docker', 'inspect', '--format', '{{.Id}}', args.image])
    identity = work / 'source-image-id.txt'
    if identity.exists() and identity.read_text().strip() != image_id:
        raise SystemExit('Source image changed since the interrupted diagnostic')
    identity.write_text(image_id + '\n')
    source_archive = work / 'source.oci.tar'
    if not source_archive.exists():
        run(['skopeo', 'copy', f'docker-daemon:{args.image}', f'oci-archive:{source_archive}'])
    repo = state / 'canonical-repo'
    cfs = ['bootc', 'internals', 'cfs', '--', '--repo', str(repo)]
    if not repo.exists():
        run([*cfs, 'init', '--insecure'])
    run([*cfs, 'oci', 'pull', '--bootable', f'oci-archive:{source_archive}', name])
    digest = capture([*cfs, 'oci', 'compute-id', '--bootable', name])
    if not re.fullmatch(r'[0-9a-f]{128}', digest):
        raise SystemExit('Unexpected canonical composefs digest')
    inputs, output = work / 'inputs', work / 'output'
    inputs.mkdir(exist_ok=True)
    output.mkdir(exist_ok=True)
    (output / 'tmp').mkdir(mode=0o700, exist_ok=True)
    container = capture(['docker', 'create', args.image, '/bin/true'])
    try:
        for path, target in [('/kernel', inputs / 'kernel'),
                             ('/usr/lib/os-release', inputs / 'os-release'),
                             ('/usr/lib/bootc/kargs.d', inputs / 'kargs')]:
            if not target.exists():
                run(['docker', 'cp', f'{container}:{path}', target])
    finally:
        run(['docker', 'rm', container])
    kernels = list((inputs / 'kernel').glob('*/vmlinuz'))
    if len(kernels) != 1:
        raise SystemExit('Expected one split kernel')
    kver = kernels[0].parent.name
    kargs = []
    for path in sorted((inputs / 'kargs').glob('*.toml')):
        data = tomllib.loads(path.read_text())
        if set(data) - {'kargs', 'match-architectures'}:
            raise SystemExit(f'Unsupported kargs config; use upstream tooling: {path.name}')
        if platform.machine() in data.get('match-architectures', [platform.machine()]):
            kargs.extend(data.get('kargs', []))
    if any(not isinstance(arg, str) or any(c.isspace() for c in arg) for arg in kargs):
        raise SystemExit('Unsupported kernel argument encoding')
    # GPT auto-discovery otherwise mounts the physical sysroot read-only. The
    # authenticated composefs stays read-only; deployment /etc and /var need rw.
    if 'ro' in kargs:
        raise SystemExit('Read-only physical root is incompatible with this persistent VM fixture')
    if 'rw' not in kargs:
        kargs.append('rw')
    kargs.append('composefs.digest=v1-sha512-12:' + digest)
    (inputs / 'cmdline').write_text(' '.join(kargs) + '\n')
    run(['docker', 'run', '--rm', '--network=none', '--read-only', '--cap-drop=ALL',
         '--user', f'{os.getuid()}:{os.getgid()}',
         '--security-opt=no-new-privileges', '--security-opt=label=disable', '--tmpfs=/tmp',
         '--env=TMPDIR=/output/tmp',
         '-v', f'{inputs}:/inputs:ro', '-v', f'{output}:/output:rw',
         '-v', f'{state / "db.key"}:/run/secrets/key:ro',
         '-v', f'{state / "db.pem"}:/run/secrets/cert:ro',
         '--entrypoint=/usr/lib/systemd/ukify', args.image,
         '--config=/dev/null', 'build', f'--linux=/inputs/kernel/{kver}/vmlinuz',
         f'--initrd=/inputs/kernel/{kver}/initramfs.img', '--cmdline=@/inputs/cmdline',
         '--os-release=@/inputs/os-release', f'--uname={kver}',
         '--secureboot-private-key=/run/secrets/key',
         '--secureboot-certificate=/run/secrets/cert', '--output=/output/kernel.efi'])
    (output / 'Containerfile').write_text(
        f'FROM {args.image}\nCOPY kernel.efi /boot/EFI/Linux/{kver}.efi\n')
    run(['docker', 'build', '-f', output / 'Containerfile', '-t', args.output_image, output])
    final_archive = work / 'sealed.oci.tar'
    run(['skopeo', 'copy', f'docker-daemon:{args.output_image}', f'oci-archive:{final_archive}'])
    run([*cfs, 'oci', 'pull', '--bootable', f'oci-archive:{final_archive}', name + '-sealed'])
    final_digest = capture([*cfs, 'oci', 'compute-id', '--bootable', name + '-sealed'])
    if final_digest != digest:
        raise SystemExit('Adding the UKI changed the bootable root; candidate remains rejected')
    report = {'source_image': args.image, 'sealed_image': args.output_image,
              'canonical_digest': digest, 'post_seal_digest': final_digest,
              'archive': str(final_archive), 'digest_stable': True,
              'scope': 'disposable VM diagnostic; strict verification remains enabled'}
    (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
