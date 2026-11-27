#!/usr/bin/env python3
"""Provision a new main-only CI boot signer with SSH-encrypted recovery escrow."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile


ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = 'closure-labs/finite'
ENVIRONMENT = 'boot-signing'
SECRET = 'FINITE_BOOT_SIGNING_KEY'


def run(command, **kwargs):
    return subprocess.run(list(map(str, command)), check=True, **kwargs)


def api(endpoint, payload=None):
    command = ['gh', 'api', 'repos/' + REPOSITORY + '/' + endpoint]
    if payload is not None:
        command += ['--method', 'PUT' if endpoint.endswith(ENVIRONMENT) else 'POST', '--input', '-']
    result = run(command, input=None if payload is None else json.dumps(payload),
                 text=True, capture_output=True)
    return json.loads(result.stdout)


def validate_policy(environment, policies):
    if environment.get('deployment_branch_policy') != {'protected_branches': False, 'custom_branch_policies': True}:
        raise ValueError('Boot signer environment must use exact custom branch restrictions')
    branches = policies.get('branch_policies', [])
    if len(branches) != 1 or branches[0].get('name') != 'main' or branches[0].get('type', 'branch') != 'branch':
        raise ValueError('Boot signer must be restricted to the main branch only')


def provision(args):
    state = args.state.resolve()
    if not state.is_relative_to(ROOT / 'artifacts') or state.exists():
        raise ValueError('Use a new private provisioning directory under checkout artifacts')
    verified = json.loads(args.backup_receipt.read_text())
    if verified.get('restoredCredentialMetadata') is not True or verified.get('passwordStoreDecrypted') is not True:
        raise ValueError('Verified credential recovery is required before creating a production signer')
    public = args.ssh_recipient.resolve(strict=True)
    private = public.with_suffix('')
    if (public.parent != Path.home() / '.ssh' or public.suffix != '.pub'
            or not private.is_file() or not public.read_text().startswith('ssh-ed25519 ')):
        raise ValueError('Use an Ed25519 public key from the backed-up SSH directory')
    destinations = [ROOT / 'sources/boot-signing.json',
                    ROOT / 'files/system/usr/share/finite/secure-boot/finite-boot.pem']
    if any(path.exists() for path in destinations):
        raise ValueError('Production signing identity already exists; use an explicit rotation procedure')
    environments = api('environments')
    if any(value['name'] == ENVIRONMENT for value in environments['environments']):
        raise ValueError('Boot-signing environment already exists; never replace its key implicitly')
    state.mkdir(parents=True, mode=0o700)
    key, cert = state / 'finite-boot.key', state / 'finite-boot.pem'
    run(['openssl', 'req', '-new', '-x509', '-newkey', 'rsa:3072', '-noenc',
         '-days', '3650', '-subj', '/CN=Finite Production Boot Signing/',
         '-addext', 'basicConstraints=critical,CA:FALSE',
         '-addext', 'keyUsage=critical,digitalSignature',
         '-addext', 'extendedKeyUsage=codeSigning', '-keyout', key, '-out', cert],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    key.chmod(0o600)
    der = subprocess.check_output(['openssl', 'x509', '-in', cert, '-outform', 'DER'])
    fingerprint = hashlib.sha256(der).hexdigest()
    metadata = {'schema': 1, 'environment': ENVIRONMENT, 'secret': SECRET,
                'repository': REPOSITORY, 'certificate': str(destinations[1].relative_to(ROOT)),
                'certificateDerSha256': fingerprint,
                'recovery': 'SSH-encrypted escrow; recover the SSH key from the verified passphrase-encrypted backup',
                'qualified': False}
    (state / 'identity.json').write_text(json.dumps(metadata, indent=2) + '\n')
    escrow = state / 'finite-boot-signer.tar.age'
    producer = subprocess.Popen(['tar', '--create', '--file=-', '--directory', str(state),
                                 'finite-boot.key', 'finite-boot.pem', 'identity.json'], stdout=subprocess.PIPE)
    try:
        encryptor = subprocess.Popen(['age', '--encrypt', '--recipients-file', str(public), '--output', str(escrow)], stdin=producer.stdout)
        producer.stdout.close()
        encryption = encryptor.wait()
        archived = producer.wait()
        if encryption or archived:
            raise ValueError('Encrypted signer escrow failed; no CI secret was installed')
    finally:
        if producer.poll() is None:
            producer.terminate()
            producer.wait()
    # Prove the escrow is recoverable before installing a remote signing secret.
    decryptor = subprocess.Popen(['age', '--decrypt', '--identity', str(private), str(escrow)],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    recovered = None
    try:
        with tarfile.open(fileobj=decryptor.stdout, mode='r|') as archive:
            for entry in archive:
                if entry.name == 'finite-boot.key' and entry.isfile():
                    recovered = archive.extractfile(entry).read()
        decryptor.stdout.close()
        decryptor.stderr.read()
        if decryptor.wait() or recovered != key.read_bytes():
            raise ValueError('Signer escrow recovery failed; no CI secret was installed')
    except tarfile.TarError as exc:
        raise ValueError('Signer escrow needs local SSH-key unlock; no CI secret was installed') from exc
    finally:
        if decryptor.poll() is None:
            decryptor.terminate()
            decryptor.wait()
    # Publish only ciphertext before allowing the production secret into CI.
    args.escrow_directory.mkdir(parents=True, exist_ok=True)
    synced = args.escrow_directory / f'finite-boot-signer-{fingerprint[:16]}.tar.age'
    with synced.open('xb') as output, escrow.open('rb') as source:
        shutil.copyfileobj(source, output)
    synced.chmod(0o600)
    api('environments/' + ENVIRONMENT, {'deployment_branch_policy': {
        'protected_branches': False, 'custom_branch_policies': True}})
    api('environments/' + ENVIRONMENT + '/deployment-branch-policies', {'name': 'main', 'type': 'branch'})
    validate_policy(api('environments/' + ENVIRONMENT),
                    api('environments/' + ENVIRONMENT + '/deployment-branch-policies'))
    with key.open('rb') as stream:
        run(['gh', 'secret', 'set', SECRET, '--repo', REPOSITORY, '--env', ENVIRONMENT], stdin=stream)
    names = json.loads(subprocess.check_output(['gh', 'secret', 'list', '--repo', REPOSITORY,
                                                '--env', ENVIRONMENT, '--json', 'name'], text=True))
    if {value['name'] for value in names} != {SECRET}:
        raise ValueError('Unexpected CI secret inventory; retain escrow and inspect provisioning')
    destinations[1].parent.mkdir(parents=True, exist_ok=True)
    with destinations[1].open('xb') as stream:
        stream.write(cert.read_bytes())
    with destinations[0].open('x') as stream:
        json.dump(metadata, stream, indent=2)
        stream.write('\n')
    for path in destinations:
        path.chmod(0o644)
    key.unlink()
    metadata.update({'provisioned': True, 'escrowFile': str(synced),
                     'escrowSha256': hashlib.sha256(escrow.read_bytes()).hexdigest(),
                     'privateWorkingCopyRemoved': True})
    (state / 'provisioned.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print('Protected CI boot signer provisioned; only the public certificate enters the image.')
    print('Public certificate DER SHA256:', fingerprint)


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state', type=Path, required=True)
    p.add_argument('--backup-receipt', type=Path, required=True)
    p.add_argument('--ssh-recipient', type=Path, required=True)
    p.add_argument('--escrow-directory', type=Path, required=True)
    args = p.parse_args()
    try:
        provision(args)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        # No command output or secret material is included in this diagnostic.
        p.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
