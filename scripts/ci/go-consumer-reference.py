#!/usr/bin/env python3
"""Authenticate explicitly selected Fedora Go consumer references on hosted runners.

No package is installed or executed. Source/caller applicability and current
candidate binding require separate review; this collector grants no clearance.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


utilities = module('consumer_reference_utilities', 'scripts/ci/freerdp-reference-evidence.py')
app = module('consumer_build_info', 'scripts/ci/applicability-evidence.py')
bounds = utilities.bounds
MAX_RPM = 64 * 1024 * 1024
DEFAULT_PACKAGES = ('buildah', 'skopeo')
RPMS = {
    'buildah': {'version': '1.43.4', 'epoch': '2', 'bytes': 10506112, 'maxBytes': 16 * 1024 * 1024,
               'build': 3103124, 'rpm': 48829555,
               'sourceCommit': 'b99f65ea1800c6488c54aff69f29336f74f6e68f'},
    'skopeo': {'version': '1.22.3', 'epoch': '1', 'bytes': 8184004, 'maxBytes': 16 * 1024 * 1024,
               'build': 3103472, 'rpm': 48834791,
               'sourceCommit': 'fb2d82ad5e8374f1f6cbe13994fe421a7b02cceb'},
    # Signed Koji object Content-Length differs from the unsigned RPM metadata.
    # This opt-in reference remains a testing candidate, not stable approval.
    'rclone': {'version': '1.75.2', 'epoch': '0', 'bytes': 33108438, 'maxBytes': 48 * 1024 * 1024,
               'build': 3118644, 'rpm': 49086983,
               'sourceCommit': '2c9e6ea83beab2b4e5fea95aabb46d7936609b8f',
               'repositoryStatusAtReview': 'updates-testing', 'approvedStableAvailable': False},
}


def reference_spec(name):
    if name not in RPMS:
        raise ValueError('Unknown reference package selector')
    spec = RPMS[name]
    if (type(spec['bytes']) is not int or type(spec['maxBytes']) is not int
            or not 0 < spec['bytes'] <= spec['maxBytes'] < MAX_RPM):
        raise ValueError('Reference requires an exact size within its reviewed package bound')
    return spec


def rpm_url(name):
    version = reference_spec(name)['version']
    return ('https://kojipkgs.fedoraproject.org/packages/' + name + '/' + version
            + '/1.fc44/data/signed/6d9f90a6/x86_64/' + name + '-' + version + '-1.fc44.x86_64.rpm')


def download(name, destination):
    expected, url = reference_spec(name)['bytes'], rpm_url(name)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            raise ValueError('Reference redirects require separate publisher review')
    with urllib.request.build_opener(NoRedirect()).open(url, timeout=30) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError('Require exact approved reference URL')
        length = response.headers.get('Content-Length')
        if length is not None and length != str(expected):
            raise ValueError('Signed reference content length mismatch')
        observed, digest = 0, hashlib.sha256()
        with destination.open('xb') as output:
            while chunk := response.read(min(bounds.CHUNK, expected + 1 - observed)):
                observed += len(chunk)
                if observed > expected:
                    raise ValueError('Signed reference download exceeds exact bound')
                output.write(chunk)
                digest.update(chunk)
        if observed != expected:
            raise ValueError('Signed reference size mismatch')
    return {'url': url, 'bytes': observed, 'sha256': digest.hexdigest()}


def metadata(name, archive, database, runner):
    spec = RPMS[name]
    fmt = '%{NAME}\t%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{SOURCERPM}\t%{FILEDIGESTALGO}\t%{VENDOR}\n'
    raw = runner(['rpm', '--dbpath', str(database), '-qp', '--qf', fmt, str(archive)])
    expected = [name, spec['epoch'], spec['version'], '1.fc44', 'x86_64',
                name + '-' + spec['version'] + '-1.fc44.src.rpm', '8', 'Fedora Project']
    if raw.strip().split('\t') != expected:
        raise ValueError('Reference name/epoch/version/source/architecture/publisher mismatch')
    fmt = '[%{FILENAMES}\t%{FILESIZES}\t%{FILEDIGESTS}\t%{FILEMODES}\n]'
    manifest = runner(['rpm', '--dbpath', str(database), '-qp', '--qf', fmt, str(archive)])
    if len(manifest.encode()) > 1024 * 1024 or len(manifest.splitlines()) > 8192:
        raise ValueError('Reference file manifest exceeds bounds')
    selected = [line.split('\t') for line in manifest.splitlines()
                if line.split('\t')[0] == '/usr/bin/' + name]
    if len(selected) != 1 or len(selected[0]) != 4:
        raise ValueError('Reference requires exactly one main executable')
    path, size, sha, mode = selected[0]
    if (not size.isascii() or not size.isdigit() or not mode.isascii() or not mode.isdigit()
            or not 0 < int(size) <= app.MAX_BINARY or int(mode) != 0o100755
            or not bounds.SHA256.fullmatch(sha)):
        raise ValueError('Reference main executable lacks bounded regular SHA256 bytes')
    return {'name': name, 'epoch': int(spec['epoch']), 'version': spec['version'],
            'release': '1.fc44', 'sourceRpm': expected[5], 'vendor': 'Fedora Project'}, {
                'mode': int(mode), 'size': int(size),
                'digest': {'algorithm': 'sha256', 'value': sha}, 'flags': ''}, manifest


def extract(name, archive, directory):
    if name not in RPMS:
        raise ValueError('Unknown reference extraction selector')
    producer = subprocess.Popen(['rpm2cpio', str(archive)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    consumer = None
    try:
        consumer = subprocess.Popen(['cpio', '--extract', '--make-directories', '--no-absolute-filenames',
            '--no-preserve-owner', '--quiet', '--directory', str(directory), '--', './usr/bin/' + name],
            stdin=producer.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        producer.stdout.close()
        producer.stdout = None
        output, error = consumer.communicate(timeout=60)
        _, producer_error = producer.communicate(timeout=60)
        if consumer.returncode or producer.returncode or len(output) + len(error) + len(producer_error) > 256 * 1024:
            raise ValueError('Reference extraction failed or exceeded output bounds')
    finally:
        for process in (consumer, producer):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate()


def collect(key, directory, runner=utilities.command, downloader=download, extractor=extract, *, package=None):
    selected = DEFAULT_PACKAGES if package is None else (package,)
    for name in selected:
        reference_spec(name)
    key_raw = utilities.read_regular(key, 65536)
    if hashlib.sha256(key_raw).hexdigest() != utilities.KEY_SHA256:
        raise ValueError('Require exact reviewed Fedora44 signing key')
    parent = utilities.parent_descriptor(directory.parent)
    try:
        if not bounds.canonical(str(directory)):
            raise ValueError('Require canonical reference output directory')
        os.mkdir(directory.name, mode=0o700, dir_fd=parent)
    finally:
        os.close(parent)
    key_copy = directory / 'fedora-44.pub'
    key_copy.write_bytes(key_raw)
    key_copy.chmod(0o400)
    database = directory / 'rpmdb'
    database.mkdir(mode=0o700)
    runner(['rpmkeys', '--dbpath', str(database), '--import', str(key_copy)])
    packages = []
    for name in selected:
        spec = reference_spec(name)
        archive = directory / (name + '.rpm')
        downloaded = downloader(name, archive)
        archive_raw = utilities.read_regular(archive, spec['maxBytes'])
        sha = hashlib.sha256(archive_raw).hexdigest()
        if downloaded != {'url': rpm_url(name), 'bytes': len(archive_raw), 'sha256': sha} or len(archive_raw) != spec['bytes']:
            raise ValueError('Reference download binding mismatch')
        signature = runner(['rpmkeys', '--dbpath', str(database), '--checksig', '--verbose', str(archive)])
        utilities.verify_signature(signature)
        (directory / (name + '-signature.txt')).write_text(signature)
        identity, expected, manifest = metadata(name, archive, database, runner)
        payload = directory / (name + '-payload')
        payload.mkdir(mode=0o700)
        extractor(name, archive, payload)
        fd = utilities.parent_descriptor(payload)
        try:
            observed = bounds.observe(fd, '/usr/bin/' + name, expected)
            if not observed['actualFileIntegrityVerified']:
                raise ValueError('Reference payload differs from authenticated RPM manifest')
        finally:
            os.close(fd)
        go = app.inspect(payload / 'usr/bin' / name)
        if go['status'] != 'platform-proven' or go['sha256'] != expected['digest']['value'] or go['size'] != expected['size']:
            raise ValueError('Go metadata is not bound to authenticated reference bytes')
        if hashlib.sha256(utilities.read_regular(archive, spec['maxBytes'])).hexdigest() != sha:
            raise ValueError('Reference archive changed during extraction')
        packages.append({'rpm': identity, 'kojiBuildId': spec['build'], 'kojiRpmId': spec['rpm'],
            'sourceCommit': spec['sourceCommit'], 'download': downloaded, 'signatureVerified': True,
            'signatureKeyFingerprint': utilities.FINGERPRINT, 'signatureKeySha256': utilities.KEY_SHA256,
            'signatureSha256': hashlib.sha256(signature.encode()).hexdigest(),
            'rpmFileManifestSha256': hashlib.sha256(manifest.encode()).hexdigest(),
            'referencePath': '/usr/bin/' + name, 'referenceBytes': observed, 'goBuildInfo': go,
            'referenceScope': 'testing-candidate' if name == 'rclone' else 'historical-signed-reference',
            'installationApproved': False, 'stableApprovalGranted': False,
            **({key: spec[key] for key in ('repositoryStatusAtReview', 'approvedStableAvailable')}
               if name == 'rclone' else {})})
    return {'schema': 1, 'status': 'signed-reference-bytes-proven', 'packages': packages,
        'observedAt': datetime.now(timezone.utc).isoformat(), 'releaseEligible': False,
        'candidateBindingUnproven': True, 'selectedPackages': list(selected), 'dispositionsGranted': [], 'vulnerabilityClearance': 'not-assessed',
        'collectorSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'supportingCollectors': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in (
            'scripts/ci/applicability-evidence.py', 'scripts/ci/rpm-file-evidence.py', 'scripts/ci/freerdp-reference-evidence.py')},
        'limits': ['No image pull, scan, package installation or payload execution.',
                   'Reference source metadata is a reviewed claim; authenticate exact build/source/caller evidence separately.',
                   'Current digest/components/aliases/all selected occurrence paths require independent byte joins.',
                   'Complete recorded module/build settings do not prove runtime callers or absent vulnerable functions.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', choices=tuple(RPMS),
                        help='Collect only this reviewed reference (default: buildah and skopeo)')
    parser.add_argument('--key', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args(argv)
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite':
        parser.error('Reference collection requires hosted Finite runners')
    try:
        report = collect(args.key, args.directory, package=args.package)
        encoded = json.dumps(report, indent=2) + '\n'
        if len(encoded.encode()) > 2 * 1024 * 1024:
            raise ValueError('Reference report exceeds bounds')
        with (args.directory / 'reference-evidence.json').open('x') as output:
            output.write(encoded)
        return 0
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
