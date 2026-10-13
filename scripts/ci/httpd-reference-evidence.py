#!/usr/bin/env python3
"""Authenticate five fixed Fedora HTTPD reference RPMs, without image work.

The supplied old-image selectors are metadata, not current byte observations.
Every unflagged regular reference file is authenticated and hashed; a separate
current-candidate join and source/advisory review must precede any disposition.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('httpd_reference_io', ROOT / 'scripts/ci/freerdp-reference-evidence.py')
io = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(io)
bounds = io.bounds
KEY_SHA256 = io.KEY_SHA256
FINGERPRINT = io.FINGERPRINT
SOURCE_COMMIT = '3b7cd5bc56d859c0b5257ffa0c5d576b85125b4c'
SOURCE_RPM = 'httpd-2.4.68-1.fc44.src.rpm'
KOJI_BUILD = 3014347
BASE_URL = 'https://kojipkgs.fedoraproject.org/packages/httpd/2.4.68/1.fc44/data/signed/6d9f90a6/'
RPMS = {
    'httpd': {'id': 47434301, 'size': 47280, 'arch': 'x86_64', 'files': 6},
    'httpd-core': {'id': 47434305, 'size': 1507266, 'arch': 'x86_64', 'files': 377},
    'httpd-filesystem': {'id': 47434287, 'size': 11509, 'arch': 'noarch', 'files': 2},
    'httpd-tools': {'id': 47434302, 'size': 81324, 'arch': 'x86_64', 'files': 6},
    'mod_lua': {'id': 47434298, 'size': 59376, 'arch': 'x86_64', 'files': 1},
}
ADVISORIES = ['CVE-2026-29167', 'GHSA-85f4-9pxx-739j']
MAX_METADATA = 2 * 1024 * 1024
MAX_COMMAND_OUTPUT = io.MAX_COMMAND_OUTPUT
MAX_MANIFEST_FILES = 1024
MAX_SELECTED_BYTES = 16 * 1024 * 1024
REGULAR_MODES = (0o100644, 0o100755, 0o100510)
UNFLAGGED_ETC_READMES = {'/etc/httpd/conf.d/README', '/etc/httpd/conf.modules.d/README'}


def filename(name):
    return name + '-2.4.68-1.fc44.' + RPMS[name]['arch'] + '.rpm'


def url(name):
    return BASE_URL + RPMS[name]['arch'] + '/' + filename(name)


def safe_path(path):
    return (isinstance(path, str) and bounds.canonical(path)
            and (path.startswith('/usr/') or path in UNFLAGGED_ETC_READMES)
            and not any(c in path for c in '*?[]\\\t\n\r\x00') and len(path) <= 4096)


def validate_mapping(mapping):
    if (not isinstance(mapping, dict) or type(mapping.get('schema')) is not int or mapping['schema'] != 1
            or type(mapping.get('kojiBuild')) is not int or mapping['kojiBuild'] != KOJI_BUILD
            or type(mapping.get('epoch')) is not int or mapping['epoch'] != 0
            or mapping.get('version') != '2.4.68' or mapping.get('release') != '1.fc44'
            or mapping.get('sourceCommit') != SOURCE_COMMIT or mapping.get('sourceRpm') != SOURCE_RPM
            or mapping.get('advisories') != ADVISORIES
            or not isinstance(mapping.get('selectorImage'), str) or not bounds.IMAGE.fullmatch(mapping['selectorImage'])
            or any(not isinstance(mapping.get(k), str) or not bounds.SHA256.fullmatch(mapping[k])
                   for k in ('sourceSummarySha256', 'sbomSha256'))
            or not isinstance(mapping.get('packages'), list) or len(mapping['packages']) != len(RPMS)):
        raise ValueError('Require the exact bounded five-RPM fixed HTTPD reference mapping')
    normalized, names, paths, total = {}, set(), set(), 0
    for package in mapping['packages']:
        if not isinstance(package, dict) or package.get('name') not in RPMS:
            raise ValueError('Unknown HTTPD reference package')
        name = package['name']
        spec = RPMS[name]
        component = ('pkg:rpm/bluefin/' + name + '@2.4.68-1.fc44?arch=' + spec['arch']
                     + '&distro=bluefin-44&upstream=' + SOURCE_RPM)
        if (name in names or package.get('component') != component
                or not isinstance(package.get('componentId'), str) or not re.fullmatch(r'[0-9a-f]{16}', package['componentId'])
                or package.get('locations') != ['/usr/share/rpm/rpmdb.sqlite']
                or package.get('observedAliases') != ['CVE-2026-29167']
                or package.get('architecture') != spec['arch']
                or type(package.get('kojiRpmId')) is not int or package['kojiRpmId'] != spec['id']
                or type(package.get('signedSize')) is not int or package['signedSize'] != spec['size']
                or package.get('signedUrl') != url(name)
                or not isinstance(package.get('files'), list) or len(package['files']) != spec['files']):
            raise ValueError('HTTPD reference identity, selector, URL, size or coverage mismatch')
        names.add(name)
        files = {}
        for entry in package['files']:
            if (not isinstance(entry, dict) or set(entry) != {'path', 'sha256', 'size', 'mode'}
                    or not safe_path(entry.get('path')) or entry['path'] in paths
                    or not isinstance(entry.get('sha256'), str) or not bounds.SHA256.fullmatch(entry['sha256'])
                    or type(entry.get('size')) is not int or not 0 <= entry['size'] <= bounds.MAX_FILE
                    or type(entry.get('mode')) is not int or entry['mode'] not in REGULAR_MODES):
                raise ValueError('Invalid duplicate/unsafe HTTPD regular-file selector')
            paths.add(entry['path'])
            total += entry['size']
            files[entry['path']] = {'mode': entry['mode'], 'size': entry['size'],
                'digest': {'algorithm': 'sha256', 'value': entry['sha256']}, 'flags': ''}
        normalized[name] = files
    if names != set(RPMS) or total > MAX_SELECTED_BYTES:
        raise ValueError('Incomplete or oversized HTTPD reference coverage')
    return normalized


def rpm_metadata(name, archive, database, runner):
    fmt = '%{NAME}\t%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{SOURCERPM}\t%{FILEDIGESTALGO}\n'
    identity = runner(['rpm', '--dbpath', str(database), '-qp', '--qf', fmt, str(archive)]).strip().split('\t')
    if identity != [name, '0', '2.4.68', '1.fc44', RPMS[name]['arch'], SOURCE_RPM, '8']:
        raise ValueError('HTTPD reference identity/epoch/source/arch/file-digest algorithm mismatch')
    fmt = '[%{FILENAMES}\t%{FILESIZES}\t%{FILEDIGESTS}\t%{FILEMODES}\t%{FILEFLAGS}\n]'
    raw = runner(['rpm', '--dbpath', str(database), '-qp', '--qf', fmt, str(archive)])
    if len(raw.encode()) > MAX_COMMAND_OUTPUT or len(raw.splitlines()) > MAX_MANIFEST_FILES:
        raise ValueError('HTTPD reference file manifest exceeds metadata bound')
    files, excluded, seen = {}, [], set()
    for line in raw.splitlines():
        fields = line.split('\t')
        if len(fields) != 5:
            raise ValueError('Malformed HTTPD reference RPM file manifest')
        path, size, digest, mode, flags = fields
        if (not bounds.canonical(path) or path in seen or any(c in path for c in '\t\n\r\x00')
                or any(not v.isascii() or not v.isdigit() for v in (size, mode, flags))):
            raise ValueError('Malformed or duplicate HTTPD reference manifest entry')
        seen.add(path)
        size, mode, flags = int(size), int(mode), int(flags)
        if not stat.S_ISREG(mode) or flags:
            excluded.append({'path': path, 'mode': mode, 'size': size, 'flags': flags,
                'reason': 'flagged-config/doc/license/ghost-or-nonregular; outside reference byte proof'})
            continue
        if (not safe_path(path) or not bounds.SHA256.fullmatch(digest)
                or mode not in REGULAR_MODES or size > bounds.MAX_FILE):
            raise ValueError('HTTPD reference target is not a bounded canonical SHA256 regular file')
        files[path] = {'mode': mode, 'size': size, 'digest': {'algorithm': 'sha256', 'value': digest}, 'flags': ''}
    if len(files) != RPMS[name]['files'] or sum(f['size'] for f in files.values()) > MAX_SELECTED_BYTES:
        raise ValueError('HTTPD reference complete regular-file coverage changed')
    return {'name': name, 'epoch': 0, 'version': '2.4.68', 'release': '1.fc44',
            'architecture': RPMS[name]['arch'], 'sourceRpm': SOURCE_RPM}, files, excluded, raw


def extract(archive, directory, paths):
    if (not paths or len(paths) > 512 or len(set(paths)) != len(paths)
            or any(not safe_path(path) for path in paths)):
        raise ValueError('Unsafe HTTPD reference extraction selection')
    selected = ['.' + path for path in sorted(paths)]
    producer = subprocess.Popen(['rpm2cpio', str(archive)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    consumer = None
    try:
        consumer = subprocess.Popen(['cpio', '--extract', '--make-directories', '--no-absolute-filenames',
            '--no-preserve-owner', '--quiet', '--directory', str(directory), '--', *selected],
            stdin=producer.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        producer.stdout.close()
        producer.stdout = None
        output, error = consumer.communicate(timeout=60)
        _, producer_error = producer.communicate(timeout=60)
        if (consumer.returncode or producer.returncode
                or len(output) + len(error) + len(producer_error) > MAX_COMMAND_OUTPUT):
            raise ValueError('Selected HTTPD reference extraction failed or exceeded output bounds')
    finally:
        for process in (consumer, producer):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate()


def collect(mapping_path, key_path, directory, runner=io.command, downloader=io.download, extractor=extract):
    raw = io.read_regular(mapping_path, MAX_METADATA)
    mapping = json.loads(raw, object_pairs_hook=bounds.unique)
    targets = validate_mapping(mapping)
    key_raw = io.read_regular(key_path, 65536)
    if hashlib.sha256(key_raw).hexdigest() != KEY_SHA256:
        raise ValueError('Fedora44 public key differs from the reviewed exact key')
    directory = Path(directory)
    parent = io.parent_descriptor(directory.parent)
    try:
        if not bounds.canonical(str(directory)):
            raise ValueError('HTTPD reference output directory must be absolute and canonical')
        os.mkdir(directory.name, mode=0o700, dir_fd=parent)
    finally:
        os.close(parent)
    key_copy = directory / 'approved-fedora-44.pub'
    with key_copy.open('xb') as output:
        output.write(key_raw)
    key_copy.chmod(0o400)
    database = directory / 'rpmdb'
    database.mkdir(mode=0o700)
    runner(['rpmkeys', '--dbpath', str(database), '--import', str(key_copy)])
    packages, matches = [], []
    for name, specification in RPMS.items():
        archive = directory / filename(name)
        downloaded = downloader(url(name), archive, specification['size'])
        archive_raw = io.read_regular(archive, io.MAX_RPM)
        archive_hash = hashlib.sha256(archive_raw).hexdigest()
        if (len(archive_raw) != specification['size'] or downloaded.get('bytes') != len(archive_raw)
                or downloaded.get('sha256') != archive_hash or downloaded.get('url') != url(name)):
            raise ValueError('HTTPD reference download binding changed before authentication')
        signature = runner(['rpmkeys', '--dbpath', str(database), '--checksig', '--verbose', str(archive)])
        io.verify_signature(signature)
        with (directory / (name + '-signature.txt')).open('x') as output:
            output.write(signature)
        identity, declared, excluded, manifest = rpm_metadata(name, archive, database, runner)
        if declared != targets[name]:
            raise ValueError('Authenticated complete HTTPD file manifest does not match selector mapping')
        payload = directory / (name + '-payload')
        payload.mkdir(mode=0o700)
        extractor(archive, payload, list(declared))
        root_fd = bounds.root_descriptor(payload)
        try:
            for path, expected in declared.items():
                observed = bounds.observe(root_fd, path, expected)
                if not observed['actualFileIntegrityVerified']:
                    raise ValueError('HTTPD reference file bytes/mode/size differ from signed manifest: ' + path)
                matches.append({'referenceRpm': name, 'referencePath': path, 'referenceBytes': observed,
                    'signedReferenceByteMatch': True, 'actualCandidateBytesIndependentlyObserved': False})
        finally:
            os.close(root_fd)
        if hashlib.sha256(io.read_regular(archive, io.MAX_RPM)).hexdigest() != archive_hash:
            raise ValueError('Authenticated HTTPD reference archive changed during collection')
        packages.append({'rpm': identity, 'kojiRpmId': specification['id'], 'download': downloaded,
            'signatureVerified': True, 'signatureSha256': hashlib.sha256(signature.encode()).hexdigest(),
            'signatureKeyFingerprint': FINGERPRINT, 'signatureKeySha256': KEY_SHA256,
            'rpmFileManifestSha256': hashlib.sha256(manifest.encode()).hexdigest(),
            'selectedFileCount': len(declared), 'excludedManifestEntries': excluded})
    return {'schema': 1, 'status': 'signed-reference-bytes-proven',
        'observedAt': datetime.now(timezone.utc).isoformat(), 'kojiBuildId': KOJI_BUILD,
        'sourceCommit': SOURCE_COMMIT, 'sourceRpm': SOURCE_RPM,
        'sourceUrl': 'https://src.fedoraproject.org/rpms/httpd/tree/' + SOURCE_COMMIT,
        'reviewedSourcePackaging': {
            'specSha256': '76366115d4901ffb2dd4480c4c6f37de5526865eebe46e01ecb8878ae6d1c93a',
            'sourceManifestSha256': '296beeb6e435d1fddd14645723056becb94bd2f9b6d6c9cb325d5fdbb42170f6',
            'sourceTarballSha512': '134a5bbd3ffe97523ac750490531bcb9441c532cedf0229aa006aa1368e9d25040507c6f519bed6754044f62c371f7c7f9a11b6a311f79b9680d478bf4373eb3',
            'review': 'Official Koji build binds exact fixed Apache2.4.68 source tarball. Fifteen immutable downstream patches were reviewed; none changes LDAP module source. Packaging splits mod_ldap; no installed-module absence or reachability claim follows.'},
        'mappingSha256': hashlib.sha256(raw).hexdigest(), 'originalSelectorImage': mapping['selectorImage'],
        'originalSelectorSbomSha256': mapping['sbomSha256'],
        'originalSelectorSummarySha256': mapping['sourceSummarySha256'],
        'originalSelectors': [{k: p[k] for k in ('component', 'componentId', 'locations', 'observedAliases')}
                              for p in mapping['packages']],
        'collectorSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'helperSha256': hashlib.sha256((ROOT / 'scripts/ci/freerdp-reference-evidence.py').read_bytes()).hexdigest(),
        'byteObserverSha256': hashlib.sha256((ROOT / 'scripts/ci/rpm-file-evidence.py').read_bytes()).hexdigest(),
        'packages': packages, 'matches': matches, 'currentCandidateJoin': 'unproven',
        'releaseEligible': False, 'dispositionsGranted': [], 'vulnerabilityClearance': 'not-assessed',
        'limits': ['No image pull, scan, installation/downgrade or image code execution performed.',
            'All unflagged regular files in five signed reference RPMs are covered. Excluded manifest entries remain outside byte proof.',
            'Old rpmdb selectors and expected digests are caller metadata, not observed current candidate bytes.',
            'Current immutable digest, component, complete aliases and every observed location need independent byte/source joins.',
            'No global LDAP absence, listener/default configuration, SELinux waiver or retained-object reachability is inferred.',
            'Production security, signing and boot qualification remain separate.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('mapping', 'key', 'directory'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(argv)
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite':
        parser.error('HTTPD reference verification requires the hosted Finite runner')
    try:
        report = collect(args.mapping, args.key, args.directory)
        encoded = json.dumps(report, indent=2) + '\n'
        if len(encoded.encode()) > MAX_METADATA:
            raise ValueError('HTTPD reference proof exceeds report bound')
        with (args.directory / 'reference-evidence.json').open('x') as output:
            output.write(encoded)
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
