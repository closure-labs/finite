#!/usr/bin/env python3
"""Authenticate one Fedora44 Podman RPM and three bounded reference payloads.

Original selector metadata is not current-candidate authority. This collector
downloads no image, installs/executes no RPM and grants no finding disposition.
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
SPEC = importlib.util.spec_from_file_location('podman_reference_utilities',
    ROOT / 'scripts/ci/freerdp-reference-evidence.py')
utilities = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(utilities)
bounds = utilities.bounds
KEY_SHA256 = '93642aec521a1e5e96dd715f7ae0ec0850ebc9de09a94ce03cae5263f26cc18a'
FINGERPRINT = '36f612dcf27f7d1a48a835e4dbfcf71c6d9f90a6'
SOURCE_COMMIT = '4d5daf480eb219a34e6c4cb96818c3d1de6d80a5'
UPSTREAM_COMMIT = 'c593b672bf3db1173aebea565ebf1a724ea196dc'
SOURCE_RPM = 'podman-5.8.7-1.fc44.src.rpm'
RPM_URL = ('https://kojipkgs.fedoraproject.org/packages/podman/5.8.7/1.fc44/'
           'data/signed/6d9f90a6/x86_64/podman-5.8.7-1.fc44.x86_64.rpm')
RPM_SPEC = {'kojiBuild': 3103127, 'kojiRpm': 48829615, 'signedBytes': 16107978,
            'unsignedKojiBytes': 16065018}
REFERENCE_PATHS = {'/usr/bin/podman', '/usr/libexec/podman/quadlet', '/usr/libexec/podman/rootlessport'}
SELECTORS = {
    '/usr/bin/podman': '/usr/bin/podman',
    '/usr/libexec/podman/quadlet': '/usr/libexec/podman/quadlet',
    '/usr/libexec/podman/rootlessport': '/usr/libexec/podman/rootlessport',
    '/sysroot/ostree/repo/objects/25/54e4b926c29889e24a1a8b6a9ed7210b3ed07f6894dceda1fd3cafebec0a12.file': '/usr/bin/podman',
    '/sysroot/ostree/repo/objects/ae/63c8b865d537e55874dbb19851e88750d162c7f2f7f171a32d8b6297d5d62a.file': '/usr/libexec/podman/rootlessport',
    '/sysroot/ostree/repo/objects/b5/fbce5322033e3ef4bd213469a251b67147c591ce89538fa8b8581784a3407c.file': '/usr/libexec/podman/quadlet',
}
ADVISORIES = {'CVE-2026-57231', 'GHSA-4hq8-gpf5-8p68', 'CVE-2025-6032',
              'GHSA-65gg-3w2w-hr4h', 'CVE-2025-9566', 'GHSA-wp3j-xq48-xpjw'}
COMPONENT = 'pkg:golang/github.com/containers/podman/v5@v5.0.0-20260916000000-a3f3696233ba%2Bdirty'
MAX_METADATA = 2 * 1024 * 1024
MAX_RPM = 32 * 1024 * 1024
MAX_FILE = 64 * 1024 * 1024
MAX_OUTPUT = 256 * 1024


def validate_mapping(mapping):
    fields = {'schema', 'status', 'selectorImage', 'sourceSummarySha256', 'sbomSha256',
              'kojiBuild', 'kojiRpm', 'epoch', 'version', 'release', 'architecture',
              'sourceCommit', 'upstreamCommit', 'sourceRpm', 'rpmUrl', 'rpmBytes',
              'component', 'advisories', 'matches'}
    if (not isinstance(mapping, dict) or set(mapping) != fields
            or type(mapping['schema']) is not int or mapping['schema'] != 1
            or type(mapping['kojiBuild']) is not int or mapping['kojiBuild'] != RPM_SPEC['kojiBuild']
            or type(mapping['kojiRpm']) is not int or mapping['kojiRpm'] != RPM_SPEC['kojiRpm']
            or type(mapping['epoch']) is not int or mapping['epoch'] != 5
            or mapping['version'] != '5.8.7' or mapping['release'] != '1.fc44'
            or mapping['architecture'] != 'x86_64' or mapping['sourceRpm'] != SOURCE_RPM
            or mapping['sourceCommit'] != SOURCE_COMMIT or mapping['upstreamCommit'] != UPSTREAM_COMMIT
            or mapping['rpmUrl'] != RPM_URL or type(mapping['rpmBytes']) is not int
            or mapping['rpmBytes'] != RPM_SPEC['signedBytes'] or mapping['component'] != COMPONENT
            or not isinstance(mapping['status'], str) or not mapping['status']
            or not isinstance(mapping['selectorImage'], str) or not bounds.IMAGE.fullmatch(mapping['selectorImage'])
            or any(not isinstance(mapping[key], str) or not bounds.SHA256.fullmatch(mapping[key])
                   for key in ('sourceSummarySha256', 'sbomSha256'))
            or not isinstance(mapping['advisories'], list) or len(mapping['advisories']) != len(ADVISORIES)
            or any(not isinstance(value, str) for value in mapping['advisories'])
            or set(mapping['advisories']) != ADVISORIES
            or not isinstance(mapping['matches'], list) or len(mapping['matches']) != len(SELECTORS)):
        raise ValueError('Require the exact reviewed Podman source/RPM/advisory mapping')
    seen, references, normalized = set(), {}, []
    for entry in mapping['matches']:
        if (not isinstance(entry, dict) or set(entry) != {'path', 'referencePath', 'sha256', 'size', 'mode'}
                or not isinstance(entry['path'], str) or entry['path'] not in SELECTORS
                or entry['path'] in seen or entry['referencePath'] != SELECTORS[entry['path']]
                or not isinstance(entry['sha256'], str) or not bounds.SHA256.fullmatch(entry['sha256'])
                or type(entry['size']) is not int or not 0 < entry['size'] <= MAX_FILE
                or type(entry['mode']) is not int or entry['mode'] != 0o100755):
            raise ValueError('Invalid Podman selector path, hash, size or regular-file mode')
        seen.add(entry['path'])
        expected = {'mode': entry['mode'], 'size': entry['size'],
                    'digest': {'algorithm': 'sha256', 'value': entry['sha256']}, 'flags': ''}
        prior = references.setdefault(entry['referencePath'], expected)
        if prior != expected:
            raise ValueError('Podman live and retained selectors disagree on reference bytes')
        normalized.append({'selectorPath': entry['path'], 'referencePath': entry['referencePath'],
                           'selectorSha256': entry['sha256'], 'selectorSize': entry['size'], 'expected': expected})
    if seen != set(SELECTORS) or set(references) != REFERENCE_PATHS:
        raise ValueError('Podman mapping omits a required selector or reference')
    return normalized, references


def download(url, destination, expected_size):
    if url != RPM_URL or expected_size != RPM_SPEC['signedBytes'] or not 0 < expected_size <= MAX_RPM:
        raise ValueError('Unapproved Podman RPM URL or size')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, response, code, message, headers, new_url):
            raise ValueError('Podman reference redirects require publisher review')
    request = urllib.request.Request(url, headers={'User-Agent': 'Finite-Podman-reference-evidence/1'})
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError('Podman reference requires the exact approved HTTPS URL')
        length = response.headers.get('Content-Length')
        if length is not None and length != str(expected_size):
            raise ValueError('Podman reference content length differs from signed-package metadata')
        observed, digest = 0, hashlib.sha256()
        with Path(destination).open('xb') as output:
            while True:
                chunk = response.read(min(bounds.CHUNK, expected_size + 1 - observed))
                if not chunk:
                    break
                observed += len(chunk)
                if observed > expected_size:
                    raise ValueError('Podman reference exceeds exact download bound')
                output.write(chunk)
                digest.update(chunk)
        if observed != expected_size:
            raise ValueError('Podman reference size differs from approved signed package')
    return {'url': url, 'bytes': observed, 'sha256': digest.hexdigest()}


def rpm_metadata(archive, database, runner):
    fmt = '%{NAME}\t%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{SOURCERPM}\t%{FILEDIGESTALGO}\t%{VENDOR}\n'
    identity = runner(['rpm', '--dbpath', str(database), '-qp', '--qf', fmt, str(archive)]).strip().split('\t')
    if identity != ['podman', '5', '5.8.7', '1.fc44', 'x86_64', SOURCE_RPM, '8', 'Fedora Project']:
        raise ValueError('Podman RPM identity/epoch/source/arch/digest/publisher mismatch')
    fmt = '[%{FILENAMES}\t%{FILESIZES}\t%{FILEDIGESTS}\t%{FILEMODES}\n]'
    raw = runner(['rpm', '--dbpath', str(database), '-qp', '--qf', fmt, str(archive)])
    if len(raw.encode()) > MAX_OUTPUT or len(raw.splitlines()) > 4096:
        raise ValueError('Podman RPM file manifest exceeds metadata bound')
    files = {}
    for line in raw.splitlines():
        fields = line.split('\t')
        if len(fields) != 4:
            raise ValueError('Malformed Podman RPM file manifest')
        path, size, digest, mode = fields
        if path not in REFERENCE_PATHS:
            continue
        if (path in files or not size.isascii() or not size.isdigit() or not mode.isascii() or not mode.isdigit()
                or not bounds.SHA256.fullmatch(digest) or int(mode) != 0o100755
                or not 0 < int(size) <= MAX_FILE):
            raise ValueError('Podman payload target must be an unambiguous bounded SHA256 regular file')
        files[path] = {'mode': int(mode), 'size': int(size),
                       'digest': {'algorithm': 'sha256', 'value': digest}, 'flags': ''}
    if set(files) != REFERENCE_PATHS:
        raise ValueError('Podman RPM omits an exact reference payload')
    return {'name': 'podman', 'epoch': 5, 'version': '5.8.7', 'release': '1.fc44',
            'architecture': 'x86_64', 'sourceRpm': SOURCE_RPM, 'vendor': 'Fedora Project'}, files, raw


def extract(archive, directory, paths):
    if len(paths) != 3 or set(paths) != REFERENCE_PATHS:
        raise ValueError('Require exactly the three approved Podman extraction paths')
    producer = subprocess.Popen(['rpm2cpio', str(archive)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    consumer = None
    try:
        consumer = subprocess.Popen(['cpio', '--extract', '--make-directories', '--no-absolute-filenames',
            '--no-preserve-owner', '--quiet', '--directory', str(directory), '--',
            *['.' + path for path in sorted(paths)]], stdin=producer.stdout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        producer.stdout.close()
        producer.stdout = None
        output, error = consumer.communicate(timeout=60)
        _, producer_error = producer.communicate(timeout=60)
        if consumer.returncode or producer.returncode or len(output) + len(error) + len(producer_error) > MAX_OUTPUT:
            raise ValueError('Podman payload extraction failed or exceeded output bound')
    finally:
        for process in (consumer, producer):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate()


def collect(mapping_path, key_path, directory, runner=utilities.command, downloader=download, extractor=extract):
    raw = utilities.read_regular(mapping_path, MAX_METADATA)
    mapping = json.loads(raw, object_pairs_hook=bounds.unique)
    targets, references = validate_mapping(mapping)
    key_raw = utilities.read_regular(key_path, 65536)
    if (hashlib.sha256(key_raw).hexdigest() != KEY_SHA256 or utilities.KEY_SHA256 != KEY_SHA256
            or utilities.FINGERPRINT != FINGERPRINT):
        raise ValueError('Podman reference requires the exact reviewed Fedora44 key and verifier')
    directory = Path(directory)
    parent = utilities.parent_descriptor(directory.parent)
    try:
        if not bounds.canonical(str(directory)):
            raise ValueError('Podman output directory must be absolute and canonical')
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
    archive = directory / 'podman-5.8.7-1.fc44.x86_64.rpm'
    downloaded = downloader(RPM_URL, archive, RPM_SPEC['signedBytes'])
    archive_raw = utilities.read_regular(archive, MAX_RPM)
    archive_hash = hashlib.sha256(archive_raw).hexdigest()
    if (len(archive_raw) != RPM_SPEC['signedBytes'] or downloaded.get('bytes') != len(archive_raw)
            or downloaded.get('sha256') != archive_hash or downloaded.get('url') != RPM_URL):
        raise ValueError('Podman download binding changed before authentication')
    signature = runner(['rpmkeys', '--dbpath', str(database), '--checksig', '--verbose', str(archive)])
    utilities.verify_signature(signature)
    with (directory / 'podman-signature.txt').open('x') as output:
        output.write(signature)
    identity, declared, manifest = rpm_metadata(archive, database, runner)
    if declared != references:
        raise ValueError('Authenticated Podman file manifest differs from selector hashes/sizes/modes')
    payload = directory / 'podman-payload'
    payload.mkdir(mode=0o700)
    extractor(archive, payload, sorted(REFERENCE_PATHS))
    root_fd, observed = bounds.root_descriptor(payload), {}
    try:
        for path, expected in sorted(references.items()):
            record = bounds.observe(root_fd, path, expected)
            if not record['actualFileIntegrityVerified']:
                raise ValueError('Podman reference payload bytes/mode/size mismatch: ' + path)
            observed[path] = record
    finally:
        os.close(root_fd)
    if hashlib.sha256(utilities.read_regular(archive, MAX_RPM)).hexdigest() != archive_hash:
        raise ValueError('Authenticated Podman archive changed during extraction')
    matches = [{**entry, 'referenceBytes': observed[entry['referencePath']], 'signedReferenceByteMatch': True,
                'actualCandidateBytesIndependentlyObserved': False} for entry in targets]
    return {'schema': 1, 'status': 'signed-reference-bytes-proven',
        'observedAt': datetime.now(timezone.utc).isoformat(), 'sourceCommit': SOURCE_COMMIT,
        'upstreamCommit': UPSTREAM_COMMIT, 'sourceRpm': SOURCE_RPM,
        'sourceUrl': 'https://src.fedoraproject.org/rpms/podman/tree/' + SOURCE_COMMIT,
        'reviewedSourcePackaging': {
            'specUrl': 'https://src.fedoraproject.org/rpms/podman/raw/' + SOURCE_COMMIT + '/f/podman.spec',
            'specSha256': '8b03b4211e85a353a41de9ec3cc892171e79a2ee989c902536a99375eae2a009',
            'manifestUrl': 'https://src.fedoraproject.org/rpms/podman/raw/' + SOURCE_COMMIT + '/f/sources',
            'manifestSha256': '7a97e5c712c59c1965e072bc7227cf184e0952523dd84cc725268ccebb752ccb',
            'sourceTarballSha512': '94a108aa9401fb62cfeaa2b3cfe8552a08240f7f9275ff53fe90eb289c285a0733b4a5582ce5f3a2c4d19d13ac9b4002f7565553d0961713a42a6101fdbe98f9',
            'review': 'Immutable Fedora spec builds upstream v5.8.7 with explicit gitCommit; autosetup initializes packaging Git and prep changes Makefile install substitution. Upstream tagged source fixes all three selected main-module advisories. These are prior source-review hashes, not a fresh source retrieval.'},
        'mappingSha256': hashlib.sha256(raw).hexdigest(), 'originalSelectorImage': mapping['selectorImage'],
        'originalSelectorSbomSha256': mapping['sbomSha256'], 'originalSelectorSummarySha256': mapping['sourceSummarySha256'],
        'component': COMPONENT, 'advisories': sorted(ADVISORIES),
        'collectorSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'supportingCollectors': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                 for name in ('scripts/ci/freerdp-reference-evidence.py', 'scripts/ci/rpm-file-evidence.py')},
        'packages': [{'rpm': identity, 'kojiBuildId': RPM_SPEC['kojiBuild'], 'kojiRpmId': RPM_SPEC['kojiRpm'],
            'download': downloaded, 'unsignedKojiBytes': RPM_SPEC['unsignedKojiBytes'],
            'signatureVerified': True, 'signatureKeyFingerprint': FINGERPRINT, 'signatureKeySha256': KEY_SHA256,
            'signatureSha256': hashlib.sha256(signature.encode()).hexdigest(),
            'rpmFileManifestSha256': hashlib.sha256(manifest.encode()).hexdigest(), 'selectedFileCount': 3}],
        'matches': matches, 'candidateBindingUnproven': True, 'releaseEligible': False,
        'dispositionsGranted': [], 'vulnerabilityClearance': 'not-assessed',
        'limits': ['No image pull, scan, RPM install or image/payload execution.',
                   'Selector metadata is a caller claim; current digest/component/aliases/all native locations must independently join the reference SHA256.',
                   'Only selected Podman main-module version matches are under investigation; compiler, embedded modules and other advisories remain separate.',
                   'No current-candidate integrity, freshness, security/signing/boot clearance is granted.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('mapping', 'key', 'directory'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(argv)
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite':
        parser.error('Podman reference verification requires the hosted Finite runner')
    try:
        report = collect(args.mapping, args.key, args.directory)
        encoded = json.dumps(report, indent=2) + '\n'
        if len(encoded.encode()) > MAX_METADATA:
            raise ValueError('Podman reference report exceeds metadata bound')
        with (args.directory / 'reference-evidence.json').open('x') as output:
            output.write(encoded)
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
