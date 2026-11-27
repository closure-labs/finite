#!/usr/bin/env python3
"""Prepare, encrypt and restore-test a workstation data backup. Never repartition."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile


REPO = Path(__file__).resolve().parents[2]
OMIT = ('.cache', '.local/share/containers', '.local/share/Steam',
        '.local/share/Trash', '.npm/_cacache', '.cargo/registry',
        '.cargo/git', '.rustup/toolchains', '.nix-defexpr', '.nix-profile',
        '.config/Nextcloud/logs', '.config/herdr/session-snapshots')
ESSENTIAL = ('.ssh', '.gnupg', '.password-store', '.config/home-manager',
             '.local/share/keyrings')
CONFIG_DIRS = ('finite', 'fish', 'gh', 'git', 'jj', 'nix', 'nixpkgs', 'ghostty',
               'espanso', 'herdr', 'opencode', 'autostart', 'environment.d',
               'fontconfig', 'gtk-3.0', 'gtk-4.0', 'goa-1.0', 'evolution',
               'systemd/user', 'containers', 'sops', 'age', 'cachix', 'tea',
               'zsh', 'micro', 'Code/User', 'VSCodium/User')
CONFIG_SUFFIXES = ('.conf', '.toml', '.json', '.jsonc', '.yaml', '.yml', '.nix',
                   '.lock', '.ini', '.rc', '.fish', '.xml', '.css', '.list', '.desktop', '.code-snippets')
CONFIG_NAMES = ('config', 'rc', 'credentials', 'settings', 'ignore', 'fish_variables')
ROOT_CONFIG = ('.bashrc', '.bash_profile', '.profile', '.zshrc', '.zprofile',
               '.zshenv', '.gitconfig', '.git-credentials', '.netrc', '.npmrc',
               '.pypirc', '.rclone.conf', '.tmux.conf', '.vimrc', '.inputrc',
               '.config/dconf/user', '.config/Nextcloud/nextcloud.cfg',
               '.aws/config', '.aws/credentials', '.kube/config',
               '.docker/config.json', '.codex/config.toml', '.codex/auth.json',
               '.codex/AGENTS.md', '.claude/settings.json', '.claude/.credentials.json')
MAX_INPUT = 512 * 1024**2


def write_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
    path.chmod(0o600)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def private(path):
    if path.is_symlink():
        raise ValueError('Working directory must not be a symlink')
    path = path.resolve()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or path.stat().st_uid != os.getuid() or stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise ValueError('Working directory must be owned by the caller with mode 0700')
    return path


def validate_paths(plan):
    """Reject exclusions that would quietly drop keys or Home Manager state."""
    home = Path(plan['home'])
    include = [Path(p) for p in plan['include']]
    exclude = [Path(p) for p in plan['exclude']]
    for essential in ESSENTIAL:
        path = home / essential
        if path.exists():
            # Absolute links in a restored credential tree could resolve back
            # to the live keys and falsely pass the decryption test.
            if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != home and parent.is_relative_to(home)):
                raise ValueError('Recovery essentials must not be symlinks; inventory their real data first')
            for parent, dirs, files in os.walk(path, followlinks=False):
                if any((Path(parent) / name).is_symlink() for name in dirs + files):
                    raise ValueError('Credential symlinks require explicit recovery handling')
            if not any(path == p or path.is_relative_to(p) for p in include):
                raise ValueError('Inventory omits recovery essentials')
            if any(path == p or path.is_relative_to(p) or p.is_relative_to(path) for p in exclude):
                raise ValueError('Exclusion removes recovery essentials')


def read_plan(path):
    plan = json.loads(path.read_text())
    if plan.get('schema') != 1 or not plan.get('include'):
        raise ValueError('Invalid backup inventory')
    home = Path(plan['home'])
    include = [Path(p) for p in plan['include']]
    exclude = [Path(p) for p in plan['exclude']]
    if any(not p.is_absolute() or p.resolve() != p for p in [home, *exclude]):
        raise ValueError('Use canonical absolute paths')
    if any(not p.is_absolute() or not p.parent.resolve().is_relative_to(home)
           or not (p.exists() or p.is_symlink()) for p in include):
        raise ValueError('Inventory includes a missing path or a path outside this home')
    validate_paths(plan)
    return plan


def inventory(args):
    home = args.home.resolve()
    work = private(args.work)
    destination = args.destination.resolve()
    if work.is_relative_to(destination):
        raise ValueError('Private working directory must be outside Nextcloud destination')
    exclude = [home / p for p in OMIT]
    exclude.extend([destination, work, REPO / 'artifacts', REPO / '.devenv', REPO / '.direnv'])
    # Configuration only: never start from the entire home, project or app tree.
    include = {home / p for p in (*ESSENTIAL, *ROOT_CONFIG)
               if (home / p).exists() or (home / p).is_symlink()}
    for name in CONFIG_DIRS:
        directory = home / '.config' / name
        if not directory.is_dir():
            continue
        for parent, dirs, files in os.walk(directory, followlinks=False):
            dirs[:] = [d for d in dirs if (Path(parent) / d) not in exclude
                       and d not in {'node_modules', '.git', '.jj', 'Cache', 'cache', 'logs',
                                     'extensions', 'globalStorage', 'workspaceStorage'}]
            for name in files:
                path = Path(parent) / name
                if (path.name.endswith(CONFIG_SUFFIXES) or path.name in CONFIG_NAMES) and path.lstat().st_size <= 512 * 1024:
                    include.add(path)
    for value in getattr(args, 'include', []):
        path = value.resolve()
        if not path.is_relative_to(home):
            raise ValueError('Additional configuration must be inside this home')
        include.add(path)
    include = sorted(include)
    plan = {'schema': 1, 'home': str(home), 'destination': str(destination),
            'include': [str(p) for p in include],
            'exclude': sorted({str(p.resolve()) for p in exclude}),
            'scope': 'small unique configuration and credentials only; no documents, downloads, repositories or installed software',
            'recoveryEssentials': list(ESSENTIAL)}
    write_json(work / 'inventory.json', plan)
    print(f'Private configuration inventory ready: {work / "inventory.json"}; {len(include)} inputs')


def check_inventory(args):
    read_plan(args.inventory)


def input_size(plan):
    excluded = {Path(p) for p in plan['exclude']}
    total = 0
    seen = set()

    def count(path):
        nonlocal total
        info = path.lstat()
        identity = (info.st_dev, info.st_ino)
        if stat.S_ISREG(info.st_mode) and identity not in seen:
            total += info.st_size + 1024
            seen.add(identity)

    def failure(_):
        raise ValueError('Cannot read a configuration input; review the private inventory')

    for value in plan['include']:
        path = Path(value)
        if any(path == p or path.is_relative_to(p) for p in excluded):
            raise ValueError('A selected configuration input is also excluded')
        if not path.is_dir() or path.is_symlink():
            count(path)
            continue
        for parent, dirs, files in os.walk(path, followlinks=False, onerror=failure):
            base = Path(parent)
            dirs[:] = [d for d in dirs if base / d not in excluded]
            for name in files:
                if base / name not in excluded:
                    count(base / name)
    return total


def metadata(plan):
    """Track restoration of credential modes and numeric ownership without contents."""
    result = {}
    for name in ESSENTIAL:
        base = Path(plan['home']) / name
        if not base.exists():
            continue
        for root, dirs, files in os.walk(base, followlinks=False):
            for path in [Path(root), *(Path(root) / n for n in dirs + files)]:
                s = path.lstat()
                if not (stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode) or stat.S_ISLNK(s.st_mode)):
                    continue
                result[str(path).lstrip('/')] = [stat.S_IMODE(s.st_mode), s.st_uid, s.st_gid]
    return result


def create(args):
    plan = read_plan(args.inventory)
    work = private(args.work)
    destination = Path(plan['destination'])
    if not any(destination == Path(p) or destination.is_relative_to(p) for p in plan['exclude']):
        raise ValueError('Backup destination must be excluded to prevent recursive backup')
    if not any(work == Path(p) or work.is_relative_to(p) for p in plan['exclude']):
        raise ValueError('Working directory must be excluded')
    archive = work / 'finite-recovery.tar.age'
    if archive.exists() or (work / 'created.json').exists():
        raise ValueError('Use a fresh inventory/work directory for each backup')
    if not os.isatty(0):
        raise ValueError('Run create in a local terminal for the age passphrase prompt')
    if args.inventory.resolve() != work / 'inventory.json':
        raise ValueError('Use the reviewed inventory.json in this working directory')
    size = input_size(plan)
    if size > MAX_INPUT:
        raise ValueError('Configuration backup exceeds 512 MiB; exclude installed data/build outputs before retrying')
    # Budget an uncompressed archive, its Nextcloud copy and a complete restore,
    # plus a reserve for the running OS. Compression can only reduce this bound.
    if shutil.disk_usage(work).free < 3 * size + 1024**3:
        raise ValueError('Insufficient free space for encryption, Nextcloud copy and full restoration')
    print(f'Configuration inputs: {size / 1024**2:.1f} MiB; backup/restore capacity checked')
    # Export trust explicitly; the home archive already includes GPG private keys.
    trust = work / 'gpg-ownertrust.txt'
    with trust.open('xb') as stream:
        subprocess.run(['gpg', '--export-ownertrust'], stdout=stream, check=True)
    trust.chmod(0o600)
    modes = metadata(plan)
    write_json(work / 'credential-metadata.json', modes)
    tar = ['tar', '--create', '--gzip', '--acls', '--xattrs', '--numeric-owner',
           '--file=-', '--anchored', '--no-wildcards']
    tar.extend('--exclude=' + p.lstrip('/') for p in plan['exclude'])
    # Explicit files from the excluded private directory are added separately.
    tar += ['--directory=/', '--null', '--verbatim-files-from', '--files-from=-',
            '--directory=' + str(work), 'gpg-ownertrust.txt', 'credential-metadata.json', 'inventory.json']
    inputs = b''.join(os.fsencode(p.lstrip('/')) + b'\0' for p in plan['include'])
    producer = subprocess.Popen(tar, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    encryptor = subprocess.Popen(['age', '--passphrase', '--output', str(archive)], stdin=producer.stdout)
    producer.stdout.close()
    try:
        producer.communicate(inputs)
        encrypted = encryptor.wait()
        if producer.returncode or encrypted:
            archive.unlink(missing_ok=True)
            raise ValueError('Backup failed, including files changing during archival; retry with applications quiesced')
    finally:
        for process in (producer, encryptor):
            if process.poll() is None:
                process.terminate()
                process.wait()
    archive.chmod(0o600)
    # The operator explicitly delegates successful upload to the Nextcloud client.
    # Copy only ciphertext; do not put inventory or owner-trust exports there.
    destination.mkdir(parents=True, exist_ok=True)
    synced = destination / f'finite-recovery-{digest(archive)[:16]}.tar.age'
    with synced.open('xb') as output, archive.open('rb') as source:
        shutil.copyfileobj(source, output)
    synced.chmod(0o600)
    write_json(work / 'created.json', {'schema': 1, 'archiveSha256': digest(archive),
               'bytes': archive.stat().st_size, 'nextcloudFile': str(synced),
               'uploadAssumedByOperator': True})
    print('Encrypted archive copied to Nextcloud. Keep the passphrase independently.')
    print('Run verify to test local restoration and password-store decryption.')


def verify(args):
    work = private(args.work)
    created = json.loads((work / 'created.json').read_text())
    original = work / 'finite-recovery.tar.age'
    archived = Path(created['nextcloudFile'])
    if digest(original) != created['archiveSha256'] or digest(archived) != created['archiveSha256']:
        raise ValueError('Nextcloud archive differs from the encrypted original')
    if not os.isatty(0):
        raise ValueError('Run verify in a local terminal for the age passphrase prompt')
    password_tested = False
    with tempfile.TemporaryDirectory(prefix='restore-', dir=work) as directory:
        restored = Path(directory)
        decryptor = subprocess.Popen(['age', '--decrypt', str(archived)], stdout=subprocess.PIPE)
        extractor = subprocess.Popen(['tar', '--extract', '--gzip', '--acls', '--xattrs',
                                      '--same-permissions', '--file=-', '--directory', directory], stdin=decryptor.stdout)
        decryptor.stdout.close()
        extraction = extractor.wait()
        decryption = decryptor.wait()
        if extraction or decryption:
            raise ValueError('Restoration failed')
        expected = json.loads((restored / 'credential-metadata.json').read_text())
        for name, values in expected.items():
            s = (restored / name).lstat()
            if [stat.S_IMODE(s.st_mode), s.st_uid, s.st_gid] != values:
                raise ValueError('Restored credential permissions or numeric ownership differ')
        # Test against restored GPG keys and password store, without printing data.
        home = json.loads((restored / 'inventory.json').read_text())['home']
        recovered_home = restored / home.lstrip('/')
        store = recovered_home / '.password-store'
        entry = args.pass_entry
        if not entry and store.is_dir():
            entries = sorted(store.rglob('*.gpg'))
            if entries:
                entry = str(entries[0].relative_to(store))[:-4]
        env = dict(os.environ, GNUPGHOME=str(recovered_home / '.gnupg'),
                   PASSWORD_STORE_DIR=str(recovered_home / '.password-store'))
        if (recovered_home / '.gnupg').is_dir():
            try:
                subprocess.run(['gpg', '--import-ownertrust', str(restored / 'gpg-ownertrust.txt')],
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                if entry:
                    subprocess.run(['pass', 'show', entry], env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                    password_tested = True
            finally:
                subprocess.run(['gpgconf', '--kill', 'gpg-agent'], env=env, check=True)
        elif entry:
            raise ValueError('Restored password store has no restored GPG home')
    write_json(work / 'verified.json', {**created, 'restoredCredentialMetadata': True,
               'passwordStoreDecrypted': password_tested})
    print('Local restoration verified; Nextcloud handles upload. No secret contents were printed.')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('inventory')
    p.add_argument('--home', type=Path, default=Path.home())
    p.add_argument('--destination', type=Path, default=Path('/var/home/dale/Nextcloud/finite-backup'))
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--include', type=Path, action='append', default=[], help='Additional small unique configuration file/directory')
    p = sub.add_parser('check-inventory')
    p.add_argument('--inventory', type=Path, required=True)
    p = sub.add_parser('create')
    p.add_argument('--inventory', type=Path, required=True)
    p.add_argument('--work', type=Path, required=True)
    p = sub.add_parser('verify')
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--pass-entry')
    args = parser.parse_args()
    try:
        globals()[args.command.replace('-', '_')](args)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
