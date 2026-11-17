#!/usr/bin/env python3
"""Prepare a fresh file-backed XBOOTLDR fixture without a helper VM or host mounts."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(*command):
    subprocess.run(list(map(str, command)), check=True)


def prepare(args):
    state = args.state.resolve()
    if not state.is_relative_to(ROOT / 'artifacts') or state.exists():
        raise ValueError('Use a fresh VM state directory under artifacts')
    bootstrap = args.bootstrap.resolve(strict=True)
    if not bootstrap.is_relative_to(ROOT / 'artifacts'):
        raise ValueError('Use an existing disposable bootstrap under artifacts')
    for name in ('installer.raw', 'OVMF_VARS.fd', 'ssh-key', 'ssh-key.pub'):
        path = bootstrap / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Bootstrap assets must be regular file-backed VM inputs')
    seal = json.loads(args.integrity.read_text())
    packages = args.runtime_packages.resolve(strict=True)
    receipt = json.loads((packages / 'receipt.json').read_text())
    pin = json.loads((packages / 'source-lock.json').read_text())
    if (seal.get('strictVerity') is not True or sha(args.archive) != seal['archiveSha256']
            or sha(packages / 'bootc-runtime.rpm') != receipt['rpmSha256']
            or sha(packages / 'source-lock.json') != receipt['sourceLockSha256']
            or receipt['sourceLockSha256'] != sha(ROOT / 'sources/bootc-runtime.json')):
        raise ValueError('Fixture archive or runtime differs from checked source evidence')
    if args.archive.stat().st_size > 4 * 1024**3:
        raise ValueError('This small fixture preparer does not budget full desktop images')
    state.mkdir(mode=0o700, parents=True)
    for name in ('installer.raw', 'OVMF_VARS.fd', 'ssh-key', 'ssh-key.pub'):
        run('cp', '--reflink=auto', '--sparse=always', '--preserve=mode', bootstrap / name, state / name)
    (state / 'installer-modules').symlink_to(bootstrap / 'installer-modules', target_is_directory=True)
    script = ROOT / 'scripts/vm-composefs/install-xbootldr.sh'
    if any(c in str(script) for c in '\n"\\'):
        raise ValueError('Unsupported debugfs source path')
    commands = state / 'debugfs-commands.txt'
    commands.write_text('rm /usr/libexec/finite-vm/install.sh\nwrite "' + str(script) +
                        '" /usr/libexec/finite-vm/install.sh\n'
                        'set_inode_field /usr/libexec/finite-vm/install.sh mode 0100755\n'
                        'set_inode_field /usr/libexec/finite-vm/install.sh uid 0\n'
                        'set_inode_field /usr/libexec/finite-vm/install.sh gid 0\n')
    run('debugfs', '-w', '-f', commands, state / 'installer.raw')
    content = subprocess.check_output(['debugfs', '-R', 'cat /usr/libexec/finite-vm/install.sh',
                                       state / 'installer.raw'], stderr=subprocess.DEVNULL)
    if content != script.read_bytes():
        raise ValueError('Bootstrap installer script was not replaced correctly')
    payload = state / 'payload'
    payload.mkdir()
    run('cp', '--reflink=auto', args.archive, payload / 'base.oci.tar')
    for source, target in [('bootc-runtime.rpm', 'bootc-runtime.rpm'),
                           ('source-lock.json', 'runtime-source.json'), ('receipt.json', 'runtime-receipt.json')]:
        shutil.copyfile(packages / source, payload / target)
    size = sum(p.stat().st_size for p in payload.iterdir()) + 768 * 1024**2
    size = ((size + 1024**2 - 1) // 1024**2) * 1024**2
    (state / 'inputs.raw').touch(mode=0o600)
    with (state / 'inputs.raw').open('r+b') as stream:
        stream.truncate(size)
    run('mkfs.ext4', '-q', '-F', '-L', 'FINITEINPUTS', '-d', payload, state / 'inputs.raw')
    run('qemu-img', 'create', '-f', 'raw', state / 'target.raw', '32G')
    entries = subprocess.check_output(['rpm', '-qp', '--qf', '[%{FILENAMES} %{FILEDIGESTS}\n]',
                                       packages / 'bootc-runtime.rpm'], text=True)
    files = {name: digest for line in entries.splitlines() if len(parts := line.split()) == 2
             for name, digest in [parts] if name in ('/usr/bin/bootc', '/usr/lib/bootc/initramfs-setup')}
    if len(files) != 2:
        raise ValueError('Runtime RPM has no complete executable identity')
    evidence = {'schema': 1, 'validationOnly': True,
                'scope': 'fresh disposable XBOOTLDR installation and boot only',
                'runtimeSource': pin, 'rpmSha256': receipt['rpmSha256'], 'runtimeFiles': files,
                'archiveSha256': seal['archiveSha256'], 'bootableRootDigest': seal['bootableRootDigest'],
                'certificateDerSha256': seal['certificateDerSha256'],
                'installerScriptSha256': sha(script), 'espMiB': 600, 'xbootldrMiB': 4096}
    (state / 'preparation.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print('Prepared isolated XBOOTLDR fixture; no host disk or firmware changes')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('state', 'bootstrap', 'archive', 'integrity', 'runtime-packages'):
        p.add_argument('--' + name, type=Path, required=True)
    prepare(p.parse_args())
