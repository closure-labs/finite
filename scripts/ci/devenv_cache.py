#!/usr/bin/env python3
"""Upload validated store roots through devenv's built-in SecretSpec integration."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
CACHE = 'https://finite-os.cachix.org'
STORE = re.compile(r'/nix/store/[a-z0-9]{32}-[^/\s]+')
CREDENTIALS = ('CACHIX_AUTH_TOKEN', 'FINITE_CACHIX_TOKEN', 'COSIGN_PRIVATE_KEY',
               'COSIGN_PASSWORD', 'MERGE_QUEUE_TOKEN', 'GH_TOKEN', 'GITHUB_TOKEN',
               'REGISTRY_TOKEN', 'RELEASE_PUBLISH_TOKEN', 'BB_PASSWORD',
               'SECAUDIT_PEM', 'SECAUDIT_CLIENTID', 'FINITE_REVIEW_PRIVATE_KEY')


def clean_env():
    return {key: value for key, value in os.environ.items()
            if key not in CREDENTIALS and not key.startswith(('SECRETSPEC_', 'GITHUB_ACTIONS_'))}


PROOF_BYTES = 1024 ** 2
PROOF_PATHS = 128


def decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate proof metadata key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def query(command):
    return subprocess.check_output(command, cwd=ROOT, env=clean_env(), text=True, timeout=300).strip()


def proof_identities():
    """Evaluate only the current repository's explicit checks, never arbitrary roots."""
    system = query(['nix', 'eval', '--file', 'lib/project-policy.nix', 'platform.system', '--raw'])
    if not re.fullmatch(r'[a-z0-9_]+-linux', system):
        raise ValueError('Invalid proof platform')
    expression = ('checks: builtins.mapAttrs (name: check: '
                  '{ drvPath = check.drvPath; outputPath = check.outPath; }) checks')
    identities = decode(query(['nix', 'eval', '--accept-flake-config', '--no-update-lock-file',
        '--no-write-lock-file', '--json', '.#checks.' + system, '--apply', expression]))
    if not isinstance(identities, dict) or not 0 < len(identities) <= PROOF_PATHS:
        raise ValueError('Invalid current check inventory')
    outputs, derivations = set(), set()
    for name, identity in identities.items():
        if (not re.fullmatch(r'[A-Za-z0-9_-]+', name) or not isinstance(identity, dict)
                or set(identity) != {'drvPath', 'outputPath'}):
            raise ValueError('Invalid current check identity')
        drv, out = identity['drvPath'], identity['outputPath']
        if (not isinstance(drv, str) or not STORE.fullmatch(drv) or not drv.endswith('.drv')
                or not isinstance(out, str) or not STORE.fullmatch(out) or out.endswith('.drv')
                or drv in derivations or out in outputs):
            raise ValueError('Ambiguous current check outputs')
        derivations.add(drv)
        outputs.add(out)
    return identities


def proof_closure(paths, identities=None):
    """Bound the deduplicated recursive union and reject every non-proof reference."""
    if (not isinstance(paths, list) or not 0 < len(paths) <= PROOF_PATHS
            or any(not isinstance(path, str) or not STORE.fullmatch(path) for path in paths)
            or len(paths) != len(set(paths))):
        raise ValueError('Invalid proof root selection')
    identities = proof_identities() if identities is None else identities
    allowed = {identity['outputPath'] for identity in identities.values()}
    if not set(paths) <= allowed:
        raise ValueError('Only current check outputs may be published')
    records = decode(query(['nix', 'path-info', '--json', '--json-format', '1', '--recursive', *sorted(paths)]))
    if (not isinstance(records, dict) or not set(paths) <= records.keys()
            or not set(records) <= allowed or not 0 < len(records) <= PROOF_PATHS):
        raise ValueError('Unexpected or oversized proof closure path inventory')
    total, normalized = 0, {}
    for path, record in records.items():
        size = record.get('narSize') if isinstance(record, dict) else None
        refs = record.get('references') if isinstance(record, dict) else None
        nar_hash = record.get('narHash') if isinstance(record, dict) else None
        if (type(size) is not int or not 0 < size <= PROOF_BYTES or not isinstance(refs, list)
                or any(not isinstance(ref, str) or ref not in records for ref in refs)
                or len(refs) != len(set(refs)) or not isinstance(nar_hash, str)
                or not re.fullmatch(r'sha256-[A-Za-z0-9+/]{43}=', nar_hash)):
            raise ValueError('Invalid proof closure size, hash or references')
        total += size
        if total > PROOF_BYTES:
            raise ValueError('Proof union exceeds 1 MiB')
        normalized[path] = {'narHash': nar_hash, 'narSize': size, 'references': sorted(refs)}
    reachable, pending = set(), list(paths)
    while pending:
        path = pending.pop()
        if path not in reachable:
            reachable.add(path)
            pending.extend(normalized[path]['references'])
    if reachable != set(records):
        raise ValueError('Unreachable entries in proof closure')
    return {'bytes': total, 'pathCount': len(normalized), 'paths': normalized}


def metadata(paths, remote=False):
    command = ['nix', 'path-info', '--json', '--json-format', '1', '--recursive']
    if remote:
        command += ['--store', CACHE]
    value = decode(subprocess.check_output(command + paths, env=clean_env(),
                                               text=True, timeout=900))
    if (not isinstance(value, dict) or not set(paths) <= value.keys()
            or len(value) > PROOF_PATHS or any(not STORE.fullmatch(path) or not isinstance(record, dict)
                or not isinstance(record.get('narHash'), str) for path, record in value.items())):
        raise ValueError('Invalid Cachix closure metadata')
    return {path: record['narHash'] for path, record in value.items()}


def run_devenv(command, *, cwd, env):
    # Own the uploader's process group as well as its temporary configuration.
    # A timeout or interrupt must not leave a credentialed daemon running.
    process = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True)
    try:
        status = process.wait(timeout=1800)
        if status:
            raise subprocess.CalledProcessError(status, command)
    finally:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=10)


def publish(paths, *, provider='local'):
    paths = list(paths)
    if (not 0 < len(paths) <= 128 or any(not isinstance(path, str) or not STORE.fullmatch(path) or path.endswith('.drv') for path in paths)
            or provider not in ('local', 'env')):
        raise ValueError('Invalid native Cachix publication request')
    env = clean_env()
    if provider == 'env':
        # Use a distinct backend key: CACHIX_AUTH_TOKEN would take devenv's
        # legacy environment shortcut rather than its built-in SecretSpec path.
        if not os.environ.get('FINITE_CACHIX_TOKEN'):
            raise ValueError('Cachix writer credential is unavailable')
        env['FINITE_CACHIX_TOKEN'] = os.environ['FINITE_CACHIX_TOKEN']
    elif any(os.environ.get(key) for key in CREDENTIALS):
        raise ValueError('Local cache publication resolves its configured backend, not inherited credentials')
    expected = proof_closure(paths)
    with tempfile.TemporaryDirectory(prefix='finite-devenv-cache-') as temporary:
        directory = Path(temporary)
        # Keep transient netrc credentials inside the owned directory even if
        # devenv is killed. Preserve keyring access to the original session bus.
        if provider == 'local' and not env.get('DBUS_SESSION_BUS_ADDRESS'):
            bus = Path(env.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'bus'
            if bus.is_socket():
                env['DBUS_SESSION_BUS_ADDRESS'] = 'unix:path=' + str(bus)
        runtime = directory / 'runtime'
        runtime.mkdir(mode=0o700)
        env['XDG_RUNTIME_DIR'] = str(runtime)
        env['TMPDIR'] = str(directory)
        # Preserve every locked input from the maintained developer environment.
        # A fresh root has no signing manifest, local overlays or cached build
        # verdicts; only the selected store paths can reach the native observer.
        yaml = (ROOT / 'devenv.yaml').read_text()
        if provider == 'env':
            settings = {'enable': True, 'provider': 'env', 'cachix_auth_token': 'FINITE_CACHIX_TOKEN'}
            yaml, replacements = re.subn(r'(?ms)^secretspec:\n.*?(?=^\S|\Z)',
                                          'secretspec: ' + json.dumps(settings) + '\n\n', yaml)
            if replacements != 1:
                raise ValueError('Expected one maintained SecretSpec configuration')
        (directory / 'devenv.yaml').write_text(yaml)
        shutil.copyfile(ROOT / 'devenv.lock', directory / 'devenv.lock')
        attributes = ['outputs.root' + str(index) for index in range(len(paths))]
        definitions = ['  ' + attr + ' = { outPath = builtins.storePath ' + json.dumps(path) + '; };'
                       for attr, path in zip(attributes, paths)]
        (directory / 'devenv.nix').write_text('{ ... }: {\n  cachix.push = "finite-os";\n'
                                             + '\n'.join(definitions) + '\n}\n')
        run_devenv(['devenv', '--no-tui', '--no-eval-cache', 'build', *attributes],
                   cwd=directory, env=env)
    # Some uploader failures are warnings and can still yield exit zero. Confirm
    # the complete closure, with anonymous reads, before reporting success.
    for attempt in range(3):
        try:
            observed = metadata(paths, remote=True)
            break
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if attempt == 2:
                raise
            time.sleep(2 ** (attempt + 1))
    if observed != {path: record['narHash'] for path, record in expected['paths'].items()}:
        raise ValueError('Cachix does not contain the complete matching closure')


def local_proofs(proof_file):
    if (proof_file.is_symlink() or not proof_file.is_file() or proof_file.stat().st_size > 65536
            or proof_file.stat().st_mode & 0o777 != 0o600 or proof_file.stat().st_uid != os.getuid()):
        raise ValueError('Invalid validated proof handoff')
    paths = proof_file.read_text().splitlines()
    if (not 0 < len(paths) <= 128 or len(paths) != len(set(paths))
            or any(not isinstance(path, str) or not STORE.fullmatch(path) or path.endswith('.drv') for path in paths)):
        raise ValueError('Invalid validated proof roots')

    publish(paths)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('proof_file', type=Path)
    local_proofs(parser.parse_args().proof_file)
