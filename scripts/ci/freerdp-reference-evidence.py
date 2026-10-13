#!/usr/bin/env python3
"""Authenticate two historical Fedora RPMs and hash twelve reference files.

No image is pulled, scanned, installed or executed. Selector-image metadata is a
caller claim: the current candidate must independently join these authenticated
reference bytes to all actual native aliases and locations before disposition.
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
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('freerdp_reference_bounds', ROOT / 'scripts/ci/rpm-file-evidence.py')
bounds = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bounds)
KEY_SHA256 = '93642aec521a1e5e96dd715f7ae0ec0850ebc9de09a94ce03cae5263f26cc18a'
FINGERPRINT = '36f612dcf27f7d1a48a835e4dbfcf71c6d9f90a6'
SOURCE_COMMIT = '199c380597cb7f4642ebd299865a3032aef4e89b'
SOURCE_RPM = 'freerdp-3.31.1-1.fc44.src.rpm'
KOJI_BUILD = 3091519
BASE_URL = 'https://kojipkgs.fedoraproject.org/packages/freerdp/3.31.1/1.fc44/data/signed/6d9f90a6/x86_64/'
RPMS = {'freerdp-libs': {'id': 48625980, 'size': 1480159},
        'libwinpr': {'id': 48625977, 'size': 439052}}
REFERENCE_PATHS = {
    '/usr/lib64/libfreerdp-shadow3.so.3.31.1': 'freerdp-libs',
    '/usr/lib64/libfreerdp-server3.so.3.31.1': 'freerdp-libs',
    '/usr/lib64/freerdp3/proxy/libproxy-bitmap-filter-plugin.so': 'freerdp-libs',
    '/usr/lib64/freerdp3/proxy/libproxy-dyn-channel-dump-plugin.so': 'freerdp-libs',
    '/usr/lib64/libfreerdp3.so.3.31.1': 'freerdp-libs',
    '/usr/lib64/libfreerdp-server-proxy3.so.3.31.1': 'freerdp-libs',
    '/usr/lib64/librdtk0.so.0.2.0': 'freerdp-libs',
    '/usr/lib64/libfreerdp-client3.so.3.31.1': 'freerdp-libs',
    '/usr/lib64/freerdp3/proxy/libproxy-demo-plugin.so': 'freerdp-libs',
    '/usr/lib64/libfreerdp-shadow-subsystem3.so.3.31.1': 'freerdp-libs',
    '/usr/lib64/libwinpr3.so.3.31.1': 'libwinpr',
    '/usr/lib64/libwinpr-tools3.so.3.31.1': 'libwinpr',
}
MAX_METADATA = 2 * 1024 * 1024
MAX_RPM = 4 * 1024 * 1024
MAX_COMMAND_OUTPUT = 256 * 1024


def parent_descriptor(path):
    value = str(path)
    if not bounds.canonical(value):
        raise ValueError('Reference parent directory must be absolute and canonical')
    base = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        return bounds.directory_at(base, Path(value).parts[1:])
    finally:
        os.close(base)


def read_regular(path, limit):
    path = Path(path)
    if not bounds.canonical(str(path)):
        raise ValueError('Reference input must be an absolute canonical file')
    parent = parent_descriptor(path.parent)
    descriptor = None
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise ValueError('Reference input is not a bounded regular file')
        raw = bytearray()
        while True:
            chunk = os.read(descriptor, min(bounds.CHUNK, limit + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
            if len(raw) > limit:
                raise ValueError('Reference input exceeds read bound')
        if (bounds.snapshot(before) != bounds.snapshot(os.fstat(descriptor))
                or bounds.snapshot(before) != bounds.snapshot(os.stat(path.name, dir_fd=parent, follow_symlinks=False))
                or len(raw) != before.st_size):
            raise ValueError('Reference input changed during observation')
        return bytes(raw)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent)


def validate_mapping(mapping):
    if (not isinstance(mapping, dict) or type(mapping.get('schema')) is not int or mapping['schema'] != 1
            or type(mapping.get('kojiBuild')) is not int or mapping['kojiBuild'] != KOJI_BUILD
            or type(mapping.get('epoch')) is not int or mapping['epoch'] != 2
            or mapping.get('sourceCommit') != SOURCE_COMMIT
            or not isinstance(mapping.get('selectorImage'), str) or not bounds.IMAGE.fullmatch(mapping['selectorImage'])
            or any(not isinstance(mapping.get(key), str) or not bounds.SHA256.fullmatch(mapping[key])
                   for key in ('sourceSummarySha256', 'sbomSha256'))
            or not isinstance(mapping.get('matches'), list) or len(mapping['matches']) != 12):
        raise ValueError('Require the exact bounded twelve-file Fedora reference mapping')
    target_paths, reference_paths, normalized = set(), set(), []
    for entry in mapping['matches']:
        matches = entry.get('officialMetadataMatches') if isinstance(entry, dict) else None
        if (not isinstance(matches, list) or len(matches) != 1 or not isinstance(matches[0], dict)
                or not isinstance(entry.get('path'), str)
                or not re.fullmatch(r'/sysroot/ostree/repo/objects/[0-9a-f]{2}/[0-9a-f]{62}\.file', entry['path'])
                or entry['path'] in target_paths or not isinstance(entry.get('sha256'), str)
                or not bounds.SHA256.fullmatch(entry['sha256']) or type(entry.get('size')) is not int
                or not 0 < entry['size'] <= 16 * 1024 * 1024):
            raise ValueError('Invalid or ambiguous native selector path/digest/size')
        match = matches[0]
        reference = match.get('referencePath')
        if (not isinstance(reference, str) or reference not in REFERENCE_PATHS
                or reference in reference_paths or match.get('rpm') != REFERENCE_PATHS[reference]
                or match.get('expectedSha256') != entry['sha256']
                or type(match.get('expectedSize')) is not int or match['expectedSize'] != entry['size']
                or type(match.get('expectedMode')) is not int or match['expectedMode'] != 0o100755):
            raise ValueError('Reference mapping does not cover the exact regular-file allowlist')
        target_paths.add(entry['path'])
        reference_paths.add(reference)
        normalized.append({'selectorPath': entry['path'], 'selectorSha256': entry['sha256'],
            'selectorSize': entry['size'], 'rpm': match['rpm'], 'referencePath': reference,
            'expected': {'mode': match['expectedMode'], 'size': entry['size'],
                         'digest': {'algorithm': 'sha256', 'value': entry['sha256']}, 'flags': ''}})
    if reference_paths != set(REFERENCE_PATHS):
        raise ValueError('Reference mapping omits a required file')
    return normalized


def command(argv):
    result = subprocess.run(argv, check=True, capture_output=True, text=True, timeout=60)
    if len(result.stdout.encode()) + len(result.stderr.encode()) > MAX_COMMAND_OUTPUT:
        raise ValueError('Reference command output exceeds evidence bound')
    return result.stdout + (('\n' + result.stderr) if result.stderr else '')


def download(url, destination, expected_size):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, response, code, message, headers, new_url):
            raise ValueError('Reference RPM redirects require separate publisher review')
    request = urllib.request.Request(url, headers={'User-Agent': 'Finite-readonly-reference-evidence/1'})
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
        if response.geturl() != url or response.status != 200:
            raise ValueError('Reference RPM must come from the exact approved HTTPS URL')
        content_length = response.headers.get('Content-Length')
        if content_length is not None and content_length != str(expected_size):
            raise ValueError('Reference RPM content length differs from exact Koji metadata')
        length = 0
        digest = hashlib.sha256()
        with Path(destination).open('xb') as output:
            while True:
                chunk = response.read(min(bounds.CHUNK, MAX_RPM + 1 - length))
                if not chunk:
                    break
                length += len(chunk)
                if length > MAX_RPM:
                    raise ValueError('Reference RPM exceeds download bound')
                output.write(chunk)
                digest.update(chunk)
        if length != expected_size:
            raise ValueError('Reference RPM size differs from exact Koji metadata')
        return {'url': url, 'sha256': digest.hexdigest(), 'bytes': length}


def verify_signature(output):
    if re.search(r'\b(?:NOKEY|NOT OK|BAD|FAILED|UNTRUSTED)\b', output, re.IGNORECASE):
        raise ValueError('Reference RPM signature or digest verification failed')
    lines = [line.strip() for line in output.splitlines() if 'signature' in line.lower()]
    signature = re.compile(r'(?:Header )?(?:OpenPGP )?V[3-6] RSA/SHA256 signature, '
        r'(?:key fingerprint: ' + FINGERPRINT + r'|key ID 6d9f90a6): OK', re.IGNORECASE)
    if (not lines or any(not signature.fullmatch(line) for line in lines)
            or not re.search(r'^\s*Payload SHA256 digest: OK\s*$', output, re.IGNORECASE | re.MULTILINE)):
        raise ValueError('Require the exact Fedora44 RSA/SHA256 signature and verified payload digest')


def rpm_metadata(name, archive, database, runner):
    fmt = '%{NAME}\t%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{SOURCERPM}\t%{FILEDIGESTALGO}\n'
    identity = runner(['rpm', '--dbpath', str(database), '-qp', '--qf', fmt, str(archive)]).strip().split('\t')
    expected = [name, '2', '3.31.1', '1.fc44', 'x86_64', SOURCE_RPM, '8']
    if identity != expected:
        raise ValueError('Reference RPM identity/epoch/source/arch/file-digest algorithm mismatch')
    fmt = '[%{FILENAMES}\t%{FILESIZES}\t%{FILEDIGESTS}\t%{FILEMODES}\n]'
    raw = runner(['rpm', '--dbpath', str(database), '-qp', '--qf', fmt, str(archive)])
    if len(raw.encode()) > MAX_COMMAND_OUTPUT or len(raw.splitlines()) > 1024:
        raise ValueError('Reference RPM file manifest exceeds metadata bound')
    files = {}
    for line in raw.splitlines():
        fields = line.split('\t')
        if len(fields) != 4:
            raise ValueError('Malformed reference RPM file manifest')
        path, size, digest, mode = fields
        if path not in REFERENCE_PATHS or REFERENCE_PATHS[path] != name:
            continue
        if (path in files or not size.isascii() or not size.isdigit() or not mode.isascii() or not mode.isdigit()
                or not bounds.SHA256.fullmatch(digest) or int(mode) != 0o100755):
            raise ValueError('Reference RPM target is not an unambiguous SHA256 regular file')
        files[path] = {'mode': int(mode), 'size': int(size), 'digest': {'algorithm': 'sha256', 'value': digest}, 'flags': ''}
    return {'name': name, 'epoch': 2, 'version': '3.31.1', 'release': '1.fc44',
            'architecture': 'x86_64', 'sourceRpm': SOURCE_RPM}, files, raw


def extract(archive, directory, paths):
    # Only these trusted, signed archive entries are selected. No scripts run,
    # no wildcard/absolute/traversal entries or archive-created symlinks selected.
    if set(paths) - set(REFERENCE_PATHS):
        raise ValueError('Unsafe reference extraction selection')
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
            raise ValueError('Selected reference payload extraction failed or exceeded output bounds')
    finally:
        for process in (consumer, producer):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate()


def collect(mapping_path, key_path, directory, runner=command, downloader=download, extractor=extract):
    raw = read_regular(mapping_path, MAX_METADATA)
    mapping = json.loads(raw, object_pairs_hook=bounds.unique)
    targets = validate_mapping(mapping)
    key_raw = read_regular(key_path, 65536)
    if hashlib.sha256(key_raw).hexdigest() != KEY_SHA256:
        raise ValueError('Fedora44 public key differs from the reviewed exact key')
    directory = Path(directory)
    parent = parent_descriptor(directory.parent)
    try:
        if not bounds.canonical(str(directory)):
            raise ValueError('Reference output directory must be canonical and absolute')
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
        filename = name + '-3.31.1-1.fc44.x86_64.rpm'
        archive = directory / filename
        downloaded = downloader(BASE_URL + filename, archive, specification['size'])
        archive_raw = read_regular(archive, MAX_RPM)
        archive_hash = hashlib.sha256(archive_raw).hexdigest()
        if (len(archive_raw) != specification['size'] or downloaded.get('bytes') != len(archive_raw)
                or downloaded.get('sha256') != archive_hash or downloaded.get('url') != BASE_URL + filename):
            raise ValueError('Reference download binding changed before authentication')
        signature = runner(['rpmkeys', '--dbpath', str(database), '--checksig', '--verbose', str(archive)])
        verify_signature(signature)
        with (directory / (name + '-signature.txt')).open('x') as output:
            output.write(signature)
        identity, declared, manifest = rpm_metadata(name, archive, database, runner)
        chosen = [entry for entry in targets if entry['rpm'] == name]
        for entry in chosen:
            if declared.get(entry['referencePath']) != entry['expected']:
                raise ValueError('Authenticated RPM file manifest does not match the native selector mapping')
        payload = directory / (name + '-payload')
        payload.mkdir(mode=0o700)
        extractor(archive, payload, [entry['referencePath'] for entry in chosen])
        root_fd = bounds.root_descriptor(payload)
        try:
            for entry in chosen:
                observed = bounds.observe(root_fd, entry['referencePath'], entry['expected'])
                if not observed['actualFileIntegrityVerified']:
                    raise ValueError('Reference file bytes/mode/size differ from authenticated expected manifest: ' + entry['referencePath'])
                matches.append({'selectorPath': entry['selectorPath'], 'selectorSha256': entry['selectorSha256'],
                    'selectorSize': entry['selectorSize'], 'referenceRpm': name, 'referencePath': entry['referencePath'],
                    'referenceBytes': observed, 'signedReferenceByteMatch': True,
                    'actualCandidateBytesIndependentlyObserved': False})
        finally:
            os.close(root_fd)
        if hashlib.sha256(read_regular(archive, MAX_RPM)).hexdigest() != archive_hash:
            raise ValueError('Authenticated reference archive changed during payload collection')
        packages.append({'rpm': identity, 'kojiRpmId': specification['id'], 'download': downloaded,
            'signatureVerified': True, 'signatureSha256': hashlib.sha256(signature.encode()).hexdigest(),
            'signatureKeyFingerprint': FINGERPRINT, 'signatureKeySha256': KEY_SHA256,
            'rpmFileManifestSha256': hashlib.sha256(manifest.encode()).hexdigest(), 'selectedFileCount': len(chosen)})
    return {'schema': 1, 'status': 'signed-reference-bytes-proven',
        'observedAt': datetime.now(timezone.utc).isoformat(), 'kojiBuildId': KOJI_BUILD,
        'sourceCommit': SOURCE_COMMIT, 'sourceRpm': SOURCE_RPM,
        'sourceUrl': 'https://src.fedoraproject.org/rpms/freerdp/tree/' + SOURCE_COMMIT,
        'reviewedSourcePackaging': {
            'specUrl': 'https://src.fedoraproject.org/rpms/freerdp/raw/' + SOURCE_COMMIT + '/f/freerdp.spec',
            'specSha256': '59e4ef58cc58a63193e6d920041b8347cd2267290fc89e0ba32d9b983d6d96d7',
            'manifestSha256': '38f2b3036c88c09da2e62b7bacf81eca3722fb20818e30883afb9b6d98169534',
            'sourceTarballSha512': 'be669db38cecfc8d774c6165a069c50249fdcb2f8877e767a10e7dc009131ed35363db50b484536f888b7ec9214cbeb1acfc3e129c9cd2694cd498b42718245e',
            'repackScriptSha256': '6cbde8ae53e1987f6e17bf3dfeec2530c7829b43ac3bf5ac9373a75c894554e0',
            'review': 'Immutable Fedora spec has no code patches; prep changes file permissions only; repack removes only unrelated winpr/crt/unicode_builtin.c. Upstream3.31.1 source guards were reviewed separately; these hashes are retained source-review evidence, not a new source download.'},
        'mappingSha256': hashlib.sha256(raw).hexdigest(), 'originalSelectorImage': mapping['selectorImage'],
        'originalSelectorSbomSha256': mapping['sbomSha256'],
        'originalSelectorSummarySha256': mapping['sourceSummarySha256'],
        'collectorSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'packages': packages, 'matches': matches, 'releaseEligible': False, 'dispositionsGranted': [],
        'vulnerabilityClearance': 'not-assessed',
        'limits': ['No image pull, native scan, RPM installation/downgrade or image code execution performed.',
                   'Original selector hashes/locations are caller metadata; this proof authenticates reference bytes, not current candidate bytes.',
                   'The exact current candidate digest, aliases, component and every native location must independently join these reference digests before any disposition.',
                   'Source-fixed advisory/platform review and production security/signing/boot qualification remain separate.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('mapping', 'key', 'directory'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(argv)
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite':
        parser.error('Reference RPM verification requires the hosted Finite runner')
    try:
        report = collect(args.mapping, args.key, args.directory)
        encoded = json.dumps(report, indent=2) + '\n'
        if len(encoded.encode()) > MAX_METADATA:
            raise ValueError('Reference proof exceeds report bound')
        with (args.directory / 'reference-evidence.json').open('x') as output:
            output.write(encoded)
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
