#!/usr/bin/env python3
"""Seal a native OCI archive using isolated host signing and canonical imports."""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import tomllib

import native_oci as oci

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('native_verify', Path(__file__).with_name('verify-native-oci.py'))
verification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verification)


def run(command, **kwargs):
    return subprocess.run(list(map(str, command)), check=True, **kwargs)


def capture(command):
    return subprocess.check_output(list(map(str, command)), text=True).strip()


def regular(root, relative):
    path = root / relative
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError('Image boot input must be a contained regular file: ' + relative)
    return path


def existing_parents(root, files):
    """Use only directory existence from unpacking; never hash mounted metadata."""
    result = set()
    for entry in files:
        for parent in PurePosixPath(entry.name).parents:
            if str(parent) == '.':
                continue
            path = root / str(parent)
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError('Boot payload parent escapes the source image')
            if path.is_dir():
                result.add(str(parent))
    return result


def kernel_arguments(root, digest):
    arguments = []
    directory = root / 'usr/lib/bootc/kargs.d'
    if directory.exists() and (directory.is_symlink() or not directory.resolve().is_relative_to(root)):
        raise ValueError('Kernel argument directory must remain inside the image')
    for path in sorted(directory.glob('*.toml')):
        data = tomllib.loads(regular(root, str(path.relative_to(root))).read_text())
        if set(data) - {'kargs', 'match-architectures'}:
            raise ValueError('Unsupported bootc kernel argument configuration')
        if 'x86_64' in data.get('match-architectures', ['x86_64']):
            values = data.get('kargs', [])
            if not isinstance(values, list):
                raise ValueError('Kernel arguments must be an array')
            arguments.extend(values)
    if any(not isinstance(arg, str) or not arg or any(c.isspace() or c == '\0' for c in arg)
           for arg in arguments):
        raise ValueError('Unsupported kernel argument encoding')
    if ('rw' not in arguments or 'ro' in arguments or any(arg.startswith(
            ('ostree=', 'composefs=', 'composefs.digest=')) for arg in arguments)):
        raise ValueError('Native input must require rw and must not override the authenticated root')
    return ' '.join([*arguments, 'composefs.digest=v1-sha512-12:' + digest])


def importer(archive, directory, bootc):
    layout = oci.extract_layout(archive, directory.parent / ('layout-' + directory.name))
    command = [bootc, 'internals', 'cfs', '--', '--repo', directory]
    run([*command, 'init', '--insecure'])
    run([*command, 'oci', 'pull', '--bootable', layout, 'candidate'])
    digest = capture([*command, 'oci', 'compute-id', '--bootable', 'candidate'])
    if not re.fullmatch('[0-9a-f]{128}', digest):
        raise ValueError('Unexpected canonical root digest')
    return digest


def remove_unpacked_tree(path):
    def writable_retry(operation, name, _):
        entry = Path(name)
        entry.parent.chmod(0o700)
        if not entry.is_symlink():
            entry.chmod(0o700)
        operation(name)

    shutil.rmtree(path, onerror=writable_retry)


def seal(args, secret):
    if args.profile not in ('finite-native', 'finite-native-dev') or not re.fullmatch('[0-9a-f]{40}', args.revision):
        raise ValueError('An exact profile and source revision are required')
    if not 0 <= args.epoch <= 4102444799:
        raise ValueError('Unsupported reproducible signing epoch')
    tools = args.tools.resolve(strict=True)
    if not tools.is_relative_to('/nix/store'):
        raise ValueError('Use the native-boot-tools output from the locked Nix toolchain')
    required = ('ukify', 'sbsign', 'sbverify', 'faketime', 'openssl', 'umoci', 'objcopy')
    if any(not (tools / 'bin' / name).is_file() for name in required):
        raise ValueError('Incomplete locked signing toolchain')
    os.environ['PATH'] = str(tools / 'bin') + ':' + os.environ['PATH']
    bootc = Path(shutil.which('bootc') or '/missing-bootc').resolve()
    pin = json.loads((ROOT / 'sources/native-composefs-verifier.json').read_text())
    if args.validation_importer_sha256 is not None and not args.validation_only:
        raise ValueError('A runner-built importer cannot be used for production sealing')
    importer_sha = verification.check_importer(bootc, pin, args.validation_importer_sha256)
    identity = json.loads((ROOT / 'sources/boot-signing.json').read_text())
    if args.validation_only:
        if not args.validation_key or not args.validation_certificate or secret:
            raise ValueError('Validation requires explicit disposable credentials and no production key')
        certificate = args.validation_certificate.resolve(strict=True)
        key_data = args.validation_key.read_bytes()
    else:
        if args.validation_key or args.validation_certificate:
            raise ValueError('Disposable keys cannot supply a production signing operation')
        if (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != identity['repository']
                or os.environ.get('GITHUB_REF') != 'refs/heads/main' or os.environ.get('GITHUB_SHA') != args.revision):
            raise ValueError('Production boot signing requires trusted same-revision main CI')
        if not secret:
            raise ValueError('Production boot signing key is missing')
        certificate = ROOT / identity['certificate']
        key_data = secret.encode()
    der = subprocess.check_output(['openssl', 'x509', '-in', certificate, '-outform', 'DER'])
    certificate_hash = hashlib.sha256(der).hexdigest()
    if not args.validation_only and certificate_hash != identity['certificateDerSha256']:
        raise ValueError('Production certificate differs from the reviewed identity')
    run(['openssl', 'x509', '-in', certificate, '-checkend', '0', '-noout'])
    source, output, work = args.source.resolve(strict=True), args.output.resolve(), args.work.resolve()
    if work.exists() or output.exists() or output == source or output.is_relative_to(work):
        raise ValueError('Use a fresh work directory and independent output archive')
    work.mkdir(mode=0o700, parents=True)
    (work / 'tmp').mkdir(mode=0o700)
    os.environ['TMPDIR'] = str(work / 'tmp')
    source_hash = oci.sha256(source)
    image = oci.Image(source)
    try:
        labels = image.config.get('config', {}).get('Labels', {})
        if image.config.get('architecture') != 'amd64' or image.config.get('os') != 'linux':
            raise ValueError('Only Linux x86_64 native candidates are supported')
        if not args.validation_only and (labels.get('io.finite.profile') != args.profile
                or labels.get('org.opencontainers.image.revision') != args.revision
                or labels.get('io.finite.boot-architecture') != 'native-composefs'):
            raise ValueError('Unsigned native root does not match the approved source/profile')
    finally:
        image.close()
    oci.extract_layout(source, work / 'oci')
    # Rootless unpack reads the signing inputs. The OCI layers used for the
    # output and root digest retain their original capability xattrs.
    run(['umoci', 'unpack', '--rootless', '--image', f'{work / "oci"}:candidate', work / 'bundle'])
    if not args.keep_work:
        shutil.rmtree(work / 'oci')
    root = work / 'bundle/rootfs'
    regular(root, 'usr/lib/composefs/setup-root-conf.toml')
    if any((root / name).exists() for name in ('usr/lib/ostree/prepare-root.conf', 'etc/ostree/prepare-root.conf', 'usr/bin/bootupctl')):
        raise ValueError('Native root retains OSTree setup or bootupd')
    kernels = list((root / 'kernel').glob('*/vmlinuz')) or list((root / 'usr/lib/modules').glob('*/vmlinuz'))
    if len(kernels) != 1:
        raise ValueError('Expected exactly one kernel payload')
    kernel = regular(root, str(kernels[0].relative_to(root)))
    initrd = regular(root, str(kernel.parent.relative_to(root)) + '/initramfs.img')
    release = kernel.parent.name
    if not re.fullmatch('[A-Za-z0-9._+-]+', release):
        raise ValueError('Unsupported kernel release')
    stub = regular(root, 'usr/lib/systemd/boot/efi/linuxx64.efi.stub')
    loader = regular(root, 'usr/lib/systemd/boot/efi/systemd-bootx64.efi')
    shim_candidates = sorted((root / 'usr/lib/efi/shim').glob('*/EFI/fedora/shimx64.efi'))
    if len(shim_candidates) != 1 and not args.validation_only:
        raise ValueError('Production root must contain one packaged Fedora shim generation')
    signed_loader, signed_uki = work / 'systemd-bootx64.efi.signed', work / 'kernel.efi'
    # Keys never enter an image, OCI layer, builder container or retained work
    # directory. Only controlled host binaries receive the private temporary file.
    with tempfile.TemporaryDirectory(prefix='finite-boot-private-', dir=os.environ.get('RUNNER_TEMP', '/tmp')) as directory:
        key = Path(directory) / 'signing.key'
        key.write_bytes(key_data)
        key.chmod(0o600)
        signing_env = dict(os.environ, TZ='UTC', FAKETIME_DONT_FAKE_MONOTONIC='1')
        signing_env.pop('FAKE_RANDOM', None)
        stamp = datetime.datetime.fromtimestamp(args.epoch, datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

        def sign(unsigned, signed):
            run(['faketime', '-f', stamp, 'sbsign', '--key', key, '--cert', certificate,
                 '--output', signed, unsigned], env=signing_env)
            run(['sbverify', '--cert', certificate, signed])

        sign(loader, signed_loader)
        files = [oci.File('usr/lib/systemd/boot/efi/systemd-bootx64.efi.signed', signed_loader),
                 oci.File('usr/lib/finite/efi/grubx64.efi', signed_loader)]
        if args.validation_only:
            files.append(oci.File('usr/share/finite/secure-boot/finite-boot.pem', certificate))
        elif regular(root, 'usr/share/finite/secure-boot/finite-boot.pem').read_bytes() != certificate.read_bytes():
            raise ValueError('Native root does not distribute the production enrollment certificate')
        payloads = {'grubx64.efi': oci.sha256(signed_loader)}
        if len(shim_candidates) == 1:
            for name in ('shimx64.efi', 'mmx64.efi'):
                path = regular(root, str((shim_candidates[0].parent / name).relative_to(root)))
                files.append(oci.File('usr/lib/finite/efi/' + name, path))
                payloads[name] = oci.sha256(path)
        files.append(oci.File('usr/lib/finite/efi/manifest.json', oci.encoded({
            'schema': 1, 'certificateDerSha256': certificate_hash, 'files': payloads})))
        if kernel.is_relative_to(root / 'usr/lib/modules'):
            for name, path in [('vmlinuz', kernel), ('initramfs.img', initrd)]:
                files.append(oci.File(f'kernel/{release}/{name}', path))
                files.append(oci.File(f'usr/lib/modules/{release}/.wh.{name}', b''))
        unsigned_root = work / 'loader-signed.oci.tar'
        oci.append(source, unsigned_root, files, existing_directories=existing_parents(root, files))
        digest = importer(unsigned_root, work / 'canonical-root', bootc)
        if not args.keep_work:
            for name in ('canonical-root', 'layout-canonical-root'):
                shutil.rmtree(work / name)
        cmdline = work / 'cmdline'
        cmdline.write_text(kernel_arguments(root, digest) + '\n')
        unsigned_uki = work / 'unsigned.efi'
        run(['ukify', '--config=/dev/null', 'build', '--linux=' + str(kernel), '--initrd=' + str(initrd),
             '--stub=' + str(stub), '--uname=' + release, '--os-release=@' + str(regular(root, 'usr/lib/os-release')),
             '--cmdline=@' + str(cmdline), '--output=' + str(unsigned_uki)],
            env=dict(os.environ, SOURCE_DATE_EPOCH=str(args.epoch)))
        sign(unsigned_uki, signed_uki)
        uki_files = [oci.File(f'boot/EFI/Linux/{release}.efi', signed_uki)]
        oci.append(unsigned_root, output, uki_files, existing_directories=existing_parents(root, uki_files))
    if args.validation_only:
        validation_loader = {'unsignedSha256': oci.sha256(loader), 'signedSha256': payloads['grubx64.efi']}
    if not args.keep_work:
        # The independent import below needs neither the signing rootfs nor
        # its intermediate archive. Release both before allocating another rootfs.
        remove_unpacked_tree(work / 'bundle')
        unsigned_root.unlink()
    # A fresh independent importer and unpack, not the signing work repository.
    (work / 'verification').mkdir(mode=0o700)
    verification.verify(argparse.Namespace(archive=output, certificate=certificate,
                         certificate_sha256=certificate_hash, output=work / 'integrity.json',
                         temporary_root=work / 'verification'), args.validation_importer_sha256)
    if oci.sha256(source) != source_hash:
        raise ValueError('Source archive changed while sealing')
    report = {'schema': 1, 'profile': args.profile, 'sourceRevision': args.revision,
              'sourceArchiveSha256': source_hash, 'archiveSha256': oci.sha256(output),
              'bootableRootDigest': digest, 'certificateDerSha256': certificate_hash,
              'kernelRelease': release, 'epoch': args.epoch, 'validationOnly': args.validation_only,
              'tools': str(tools), 'importerSha256': importer_sha,
              'integrity': json.loads((work / 'integrity.json').read_text())}
    if args.validation_only:
        report['validationLoader'] = validation_loader
    with (work / 'sealed.json').open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    if not args.keep_work:
        for name in ('verification', 'tmp'):
            remove_unpacked_tree(work / name)
        for name in ('unsigned.efi', 'kernel.efi', 'systemd-bootx64.efi.signed', 'cmdline'):
            (work / name).unlink()
    print('Native archive sealed and independently verified; validationOnly=' + str(args.validation_only).lower())


def main():
    os.umask(0o077)
    # Strip the secret before any child process or image input is inspected.
    secret = os.environ.pop('FINITE_BOOT_SIGNING_KEY', '')
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'output', 'work', 'tools'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--profile', required=True)
    p.add_argument('--revision', required=True)
    p.add_argument('--epoch', type=int, required=True)
    p.add_argument('--validation-only', action='store_true')
    p.add_argument('--keep-work', action='store_true')
    p.add_argument('--validation-key', type=Path)
    p.add_argument('--validation-certificate', type=Path)
    p.add_argument('--validation-importer-sha256', help='same-run Nix-built importer identity for disposable CI')
    args = p.parse_args()
    try:
        seal(args, secret)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        p.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
