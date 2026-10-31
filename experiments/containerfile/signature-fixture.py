#!/usr/bin/env python3
"""Disposable loopback-only signature compatibility test, never a publisher."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

REGISTRY = 'docker.io/library/registry@sha256:1290056e2357eceb0c047cb60ae9abb370305a218e2df650eb8d3ea021b1c151'
ERROR = re.compile(r'invalid signature|no matching signatures|none of the signatures|signature verification failed|a signature was required|no signature exists|signature.*(?:identity|digest)|(?:identity|digest).*signature', re.I)


def run(*args, env=None, reject=False):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env, timeout=120)
    if reject:
        if result.returncode == 0 or not ERROR.search(result.stderr):
            raise RuntimeError('Expected a signature-policy rejection, not success or infrastructure failure: ' + result.stderr[-2000:])
    elif result.returncode:
        raise RuntimeError('Fixture command failed: ' + args[0] + ': ' + result.stderr[-2000:])
    return result.stdout.strip()


def policy(repo, key):
    return {'default': [{'type': 'reject'}], 'transports': {'docker': {repo: [{
        'type': 'sigstoreSigned', 'keyPath': str(key), 'signedIdentity': {'type': 'matchRepository'}}]}}}


def isolated_environment(work):
    # Never inherit registry credentials, COSIGN_REPOSITORY, ambient OIDC or authfile overrides.
    auth = work / 'auth.json'
    auth.write_text('{"auths":{}}')
    os.chmod(auth, 0o600)
    return {'PATH': os.environ['PATH'], 'LANG': 'C.UTF-8', 'HOME': str(work),
            'DOCKER_CONFIG': str(work / 'docker'), 'REGISTRY_AUTH_FILE': str(auth),
            'XDG_CONFIG_HOME': str(work / 'config'), 'COSIGN_PASSWORD': ''}


def image(directory, label):
    blobs = directory / 'blobs/sha256'
    blobs.mkdir(parents=True)
    def blob(value, media):
        data = json.dumps(value, sort_keys=True).encode()
        digest = hashlib.sha256(data).hexdigest()
        (blobs / digest).write_bytes(data)
        return {'mediaType': media, 'digest': 'sha256:' + digest, 'size': len(data)}
    config = blob({'architecture': 'amd64', 'os': 'linux', 'config': {'Labels': {'fixture': label}},
                   'rootfs': {'type': 'layers', 'diff_ids': []}}, 'application/vnd.oci.image.config.v1+json')
    manifest = blob({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                     'config': config, 'layers': []}, 'application/vnd.oci.image.manifest.v1+json')
    manifest['annotations'] = {'org.opencontainers.image.ref.name': 'fixture'}
    (directory / 'index.json').write_text(json.dumps({'schemaVersion': 2, 'manifests': [manifest]}))
    (directory / 'oci-layout').write_text('{"imageLayoutVersion":"1.0.0"}')
    return manifest['digest']


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_EVENT_NAME') != 'pull_request':
        raise RuntimeError('Hosted internal PR experiment only')
    spec = importlib.util.spec_from_file_location('prepare', Path(__file__).with_name('prepare.py'))
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)
    revision = prepare.authorized_revision()
    if run('git', 'rev-parse', 'HEAD') != revision:
        raise RuntimeError('Checkout differs from authorized head')
    version = run('cosign', 'version', '--json')
    if json.loads(version).get('gitVersion', '').lstrip('v') != '3.1.3':
        raise RuntimeError('Fixture requires the production Cosign 3.1.3 cohort')
    output = Path('.bluebuild/signature-fixture/result.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix='finite-signature-', dir='/tmp') as temp:
        work = Path(temp)
        os.chmod(work, 0o700)
        env = isolated_environment(work)
        container = run('docker', 'run', '-d', '--rm', '--read-only', '--tmpfs', '/var/lib/registry',
                        '-p', '127.0.0.1::5000', REGISTRY, env=env)
        try:
            port = run('docker', 'port', container, '5000/tcp', env=env)
            if not re.fullmatch(r'127\.0\.0\.1:[0-9]+', port):
                raise RuntimeError('Registry not loopback-bound')
            registry = port
            for _ in range(30):
                import urllib.request
                try:
                    with urllib.request.urlopen('http://' + registry + '/v2/', timeout=1):
                        break
                except OSError:
                    time.sleep(1)
            else:
                raise RuntimeError('Local registry did not become ready')
            repos = {name: registry + '/' + name for name in ('signed', 'unsigned', 'substituted')}
            for name in ('key', 'wrong'):
                run('cosign', 'generate-key-pair', '--output-key-prefix', str(work / name), env=env)
                os.chmod(work / (name + '.key'), 0o600)
            digest = image(work / 'original', 'original')
            changed = image(work / 'changed', 'changed')
            # Setup copies only to the disposable registry. Verification uses a separate reject policy.
            for name in repos:
                run('skopeo', '--insecure-policy', 'copy', '--dest-tls-verify=false', '--preserve-digests',
                    'oci:' + str(work / 'original') + ':fixture', 'docker://' + repos[name] + ':fixture', env=env)
            run('skopeo', '--insecure-policy', 'copy', '--dest-tls-verify=false', '--preserve-digests',
                'oci:' + str(work / 'changed') + ':fixture', 'docker://' + repos['signed'] + ':changed', env=env)
            target = repos['signed'] + '@' + digest
            run('cosign', 'sign', '--yes', '--new-bundle-format=false', '--use-signing-config=false',
                '--tlog-upload=false', '--allow-http-registry', '--key', str(work / 'key.key'), target, env=env)
            run('cosign', 'verify', '--new-bundle-format=false', '--insecure-ignore-tlog',
                '--allow-http-registry', '--key', str(work / 'key.pub'), target, env=env)
            configs = work / 'registries.d'
            configs.mkdir()
            (configs / 'fixture.yaml').write_text('docker:\n  "' + registry + '":\n    use-sigstore-attachments: true\n')
            results = {}
            def verify(name, repo, value, key='key', reject=False):
                path = work / (name + '-policy.json')
                path.write_text(json.dumps(policy(repo, work / (key + '.pub'))))
                run('skopeo', '--policy', str(path), '--registries.d', str(configs), 'copy',
                    '--src-tls-verify=false', 'docker://' + repo + '@' + value,
                    'dir:' + str(work / ('verified-' + name)), env=env, reject=reject)
                results[name] = {'outcome': 'rejected' if reject else 'accepted',
                                 'policySha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            verify('signed', repos['signed'], digest)
            verify('unsigned', repos['unsigned'], digest, reject=True)
            verify('wrong-key', repos['signed'], digest, key='wrong', reject=True)
            signature_tag = 'sha256-' + digest.split(':')[1] + '.sig'
            for name, value in (('repository-substitution', digest), ('digest-substitution', changed)):
                repo = repos['substituted'] if name.startswith('repository') else repos['signed']
                destination_tag = 'sha256-' + value.split(':')[1] + '.sig'
                run('skopeo', '--insecure-policy', 'copy', '--src-tls-verify=false', '--dest-tls-verify=false',
                    'docker://' + repos['signed'] + ':' + signature_tag,
                    'docker://' + repo + ':' + destination_tag, env=env)
                verify(name, repo, value, reject=True)
            receipt = {'schema': 1, 'sourceRevision': revision, 'testFixtureOnly': True,
                       'authorizesPublication': False, 'productionUpgradeValidated': False,
                       'registryImage': REGISTRY, 'cosignVersion': json.loads(version),
                       'skopeoVersion': run('skopeo', '--version'), 'digest': digest, 'changedDigest': changed,
                       'registriesConfigSha256': hashlib.sha256((configs / 'fixture.yaml').read_bytes()).hexdigest(),
                       'publicKeySha256': hashlib.sha256((work / 'key.pub').read_bytes()).hexdigest(),
                       'outcomes': results}
            output.write_text(json.dumps(receipt, indent=2) + '\n')
        finally:
            run('docker', 'rm', '-f', container, env=env)


if __name__ == '__main__':
    main()
