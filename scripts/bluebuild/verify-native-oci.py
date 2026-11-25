#!/usr/bin/env python3
"""Independently import a final OCI archive and verify its signed UKI root digest."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import native_oci as oci


ROOT = Path(__file__).resolve().parents[2]


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def capture(command):
    return subprocess.check_output(list(map(str, command)), text=True).strip()


def run(command):
    subprocess.run(list(map(str, command)), check=True)


def digest_arguments(cmdline):
    """Require strict, unambiguous V1 verification; reject optional/fallback roots."""
    args = cmdline.strip('\0\n ').split()
    digests = [arg for arg in args if arg.startswith(('composefs=', 'composefs.digest='))]
    if len(digests) != 1 or not re.fullmatch(r'composefs.digest=v1-sha512-12:[0-9a-f]{128}', digests[0]):
        raise ValueError('Expected exactly one strict V1 composefs digest in the signed UKI')
    if 'rw' not in args or 'ro' in args or any(arg.startswith('ostree=') for arg in args):
        raise ValueError('UKI must use a writable physical sysroot and the native backend')
    return digests[0].rsplit(':', 1)[1]


def verify(args):
    for tool in ('bootc', 'openssl', 'umoci', 'sbverify', 'objcopy'):
        if not shutil.which(tool):
            raise ValueError('Missing canonical verification tool: ' + tool)
    lock = json.loads((ROOT / 'sources/native-composefs-verifier.json').read_text())
    bootc = Path(shutil.which('bootc') or '/missing-bootc').resolve()
    if (platform.machine() != lock['architecture'] or sha256(bootc) not in {lock['bootcSha256'], *lock.get('additionalBootcSha256', [])}
            or capture([bootc, '--version']) != lock['bootcVersion']):
        raise ValueError('Canonical importer differs from its reviewed version/binary pin')
    archive = args.archive.resolve(strict=True)
    certificate = args.certificate.resolve(strict=True)
    if not re.fullmatch(r'[0-9a-f]{64}', args.certificate_sha256):
        raise ValueError('Supply the reviewed production certificate DER SHA256')
    der = subprocess.check_output(['openssl', 'x509', '-in', certificate, '-outform', 'DER'])
    if hashlib.sha256(der).hexdigest() != args.certificate_sha256:
        raise ValueError('Signing certificate differs from the reviewed production identity')
    run(['openssl', 'x509', '-in', certificate, '-checkend', '0', '-noout'])
    if args.output.exists():
        raise ValueError('Refusing to overwrite verification evidence')
    archive_hash = sha256(archive)
    # A new repository for every final image prevents cached roots from masking
    # a bad archive. Insecure build storage does not relax installed fs-verity.
    with tempfile.TemporaryDirectory(prefix='finite-native-import-', dir=getattr(args, 'temporary_root', None)) as directory:
        work = Path(directory)
        cfs = [bootc, 'internals', 'cfs', '--', '--repo', work / 'repo']
        layout = oci.extract_layout(archive, work / 'oci')
        run([*cfs, 'init', '--insecure'])
        run([*cfs, 'oci', 'pull', '--bootable', layout, 'candidate'])
        imported = capture([*cfs, 'oci', 'compute-id', '--bootable', 'candidate'])
        if not re.fullmatch(r'[0-9a-f]{128}', imported):
            raise ValueError('Importer produced an unexpected bootable-root digest')
        shutil.rmtree(work / 'repo')
        # Unpack separately from the importer. Neither this tree's ownership
        # nor Docker's mounted metadata is used to compute the authenticated root.
        run(['umoci', 'unpack', '--rootless', '--image', f'{work / "oci"}:candidate', work / 'bundle'])
        rootfs = work / 'bundle/rootfs'
        uki_dir = rootfs / 'boot/EFI/Linux'
        ukis = sorted(uki_dir.glob('*.efi'))
        if not ukis or uki_dir.resolve() != uki_dir:
            raise ValueError('Completed image has no independent UKI directory')
        verified = []
        for index, uki in enumerate(ukis):
            if not uki.is_file() or uki.resolve() != uki:
                raise ValueError('UKI must be a regular image file')
            run(['sbverify', '--cert', certificate, uki])
            section = work / f'cmdline-{index}'
            run(['objcopy', '-O', 'binary', '--only-section=.cmdline', uki, section])
            if digest_arguments(section.read_text()) != imported:
                raise ValueError('Signed UKI root digest differs from the independently imported final OCI')
            verified.append({'path': str(uki.relative_to(rootfs)), 'sha256': sha256(uki)})
        if sha256(archive) != archive_hash:
            raise ValueError('OCI archive changed during verification')
        report = {'schema': 1, 'archiveSha256': archive_hash,
                  'bootableRootDigest': imported, 'strictVerity': True,
                  'certificateDerSha256': args.certificate_sha256,
                  'importerBinarySha256': sha256(bootc),
                  'importer': lock, 'ukis': verified,
                  'scope': 'artifact integrity only; not release or migration approval'}
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print('Every signed UKI matches the independently imported final OCI root.')


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--certificate', type=Path, required=True)
    p.add_argument('--certificate-sha256', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--temporary-root', type=Path)
    args = p.parse_args()
    try:
        verify(args)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        p.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
