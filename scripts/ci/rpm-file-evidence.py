#!/usr/bin/env python3
"""Hosted, bounded byte evidence for selected native RPM file manifests.

The caller authenticates and extracts the immutable image. RPM digests and
signatures here are untrusted catalog metadata bound by the raw SBOM hash;
matching file bytes do not verify RPM signatures or grant a disposition.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from urllib.parse import unquote

TARGETS = {'curl', 'libcurl', 'libcurl-minimal', 'httpd', 'httpd-core',
           'httpd-tools', 'httpd-filesystem', 'mod_lua'}
MAX_SBOM = 256 * 1024 * 1024
MAX_FILE = 256 * 1024 * 1024
MAX_FILES = 512
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_ROWS = 4096
MAX_OUTPUT = 8 * 1024 * 1024
CHUNK = 1024 * 1024
IMAGE = re.compile(r'ghcr\.io/closure-labs/finite@sha256:[0-9a-f]{64}')
SHA256 = re.compile(r'[0-9a-f]{64}')


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate native SBOM JSON key')
        result[key] = value
    return result


def canonical(value):
    return (isinstance(value, str) and 0 < len(value) <= 4096
            and value.startswith('/') and not value.startswith('//')
            and not any(ord(char) < 32 or ord(char) == 127 for char in value)
            and '..' not in PurePosixPath(value).parts
            and PurePosixPath(value).as_posix() == value)


def snapshot(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink, info.st_uid, info.st_gid)


def stat_record(info):
    return {'device': info.st_dev, 'inode': info.st_ino, 'mode': info.st_mode,
            'size': info.st_size, 'mtimeNs': info.st_mtime_ns,
            'ctimeNs': info.st_ctime_ns, 'linkCount': info.st_nlink,
            'uid': info.st_uid, 'gid': info.st_gid}


def directory_at(start_fd, parts):
    """Every component is opened relative to its verified directory descriptor."""
    current = os.dup(start_fd)
    try:
        for part in parts:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=current)
            os.close(current)
            current = child
        return current
    except BaseException:
        os.close(current)
        raise


def root_descriptor(rootfs):
    value = os.fspath(rootfs)
    if not canonical(value) or value == '/':
        raise ValueError('Rootfs must be an absolute canonical extracted directory, not the host root')
    base = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        return directory_at(base, PurePosixPath(value).parts[1:])
    finally:
        os.close(base)


def read_sbom(path):
    """Called only after the CLI hosted guard; fixtures use tiny documents."""
    value = os.fspath(path)
    if not canonical(value):
        raise ValueError('SBOM path must be absolute and canonical')
    base = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    parent = None
    fd = None
    try:
        parts = PurePosixPath(value).parts[1:]
        parent = directory_at(base, parts[:-1])
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_SBOM:
            raise ValueError('Native SBOM must be a bounded nonempty regular file')
        raw = bytearray()
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, min(CHUNK, MAX_SBOM + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
            digest.update(chunk)
            if len(raw) > MAX_SBOM:
                raise ValueError('Native SBOM exceeds read bound')
        after = os.fstat(fd)
        entry = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        if snapshot(before) != snapshot(after) or snapshot(before) != snapshot(entry) or len(raw) != before.st_size:
            raise ValueError('Native SBOM changed during observation')
        return json.loads(raw, object_pairs_hook=unique), digest.hexdigest()
    finally:
        if fd is not None:
            os.close(fd)
        if parent is not None:
            os.close(parent)
        os.close(base)


def declared_path(item, prefix):
    value = item.get('path')
    if isinstance(value, str) and value.startswith(prefix + '/'):
        value = value[len(prefix):]
    return value if canonical(value) and value != '/' else None


def observe(root_fd, path, expected):
    record = {'path': path, 'status': 'unknown', 'actualFileIntegrityVerified': False,
              'expected': {key: expected.get(key) for key in ('mode', 'size', 'digest', 'flags', 'userName', 'groupName')}}
    flags = expected.get('flags', '')
    mode, size, digest = expected.get('mode'), expected.get('size'), expected.get('digest')
    if not isinstance(flags, str) or len(flags) > 64:
        record['reason'] = 'malformed-rpm-file-flags'
        return record
    if 'g' in flags:
        record['reason'] = 'ghost-file-not-byte-qualified'
        return record
    if type(mode) is not int or not 0 <= mode <= 0xffff:
        record['reason'] = 'unknown-declared-file-mode'
        return record
    if not stat.S_ISREG(mode):
        record['reason'] = 'declared-symlink-or-nonregular-file'
        return record
    if (type(size) is not int or not 0 <= size <= MAX_FILE or not isinstance(digest, dict)
            or digest.get('algorithm') != 'sha256' or not isinstance(digest.get('value'), str)
            or not SHA256.fullmatch(digest['value'])):
        record['reason'] = 'unsupported-or-unbounded-expected-digest-size'
        return record
    parts = PurePosixPath(path).parts[1:]
    parent = fd = check_parent = None
    try:
        parent = directory_at(root_fd, parts[:-1])
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        before = os.fstat(fd)
        record['observedStat'] = stat_record(before)
        if not stat.S_ISREG(before.st_mode):
            record['reason'] = 'actual-file-not-regular'
            return record
        if before.st_size > MAX_FILE:
            record['reason'] = 'actual-file-exceeds-size-bound'
            return record
        # Do not spend runner time reading an already disproven size.
        if before.st_size != size:
            record['reason'] = 'config-size-difference' if 'c' in flags else 'size-mismatch'
            return record
        hashed = hashlib.sha256()
        observed = 0
        prefix = b''
        while True:
            chunk = os.read(fd, min(CHUNK, MAX_FILE + 1 - observed))
            if not chunk:
                break
            if not prefix:
                prefix = chunk[:20]
            observed += len(chunk)
            if observed > MAX_FILE:
                raise ValueError('Actual file exceeds streaming bound')
            hashed.update(chunk)
        record.update(actualSha256=hashed.hexdigest(), bytesRead=observed,
                      elfHeader=prefix.hex() if prefix.startswith(b'\x7fELF') else None)
        after = os.fstat(fd)
        check_parent = directory_at(root_fd, parts[:-1])
        entry = os.stat(parts[-1], dir_fd=check_parent, follow_symlinks=False)
        record['afterStat'] = stat_record(after)
        if snapshot(before) != snapshot(after) or snapshot(before) != snapshot(entry) or observed != before.st_size:
            record['reason'] = 'file-or-path-changed-during-observation'
            return record
        if hashed.hexdigest() != digest['value']:
            record['reason'] = 'config-digest-difference' if 'c' in flags else 'digest-mismatch'
            return record
        if stat.S_IMODE(before.st_mode) != stat.S_IMODE(mode):
            record['reason'] = 'file-mode-difference'
            return record
        record.update(status='matches-rpm-manifest', actualFileIntegrityVerified=True,
                      reason='stable-regular-file-size-sha256-and-mode-match',
                      configFile='c' in flags)
        return record
    except (OSError, ValueError) as error:
        record['reason'] = 'missing-symlink-unsafe-or-unreadable-file'
        record['error'] = str(error)[:256]
        return record
    finally:
        for descriptor in (check_parent, fd, parent):
            if descriptor is not None:
                os.close(descriptor)


def package_identity(artifact):
    metadata = artifact.get('metadata')
    if not isinstance(metadata, dict):
        raise ValueError('Selected RPM requires native metadata')
    identity = {key: artifact.get(key) for key in ('id', 'name', 'version', 'purl', 'foundBy', 'metadataType')}
    identity.update({key: metadata.get(key) for key in ('name', 'version', 'release', 'epoch',
                    'architecture', 'sourceRpm', 'vendor', 'signatures')})
    identity['catalogVersion'] = artifact.get('version')
    problems = []
    name, version, release = metadata.get('name'), metadata.get('version'), metadata.get('release')
    if (name != artifact.get('name') or not isinstance(version, str) or not version
            or not isinstance(release, str) or not re.fullmatch(r'[0-9A-Za-z_.+]+', release)
            or metadata.get('epoch') not in (None, 0) or type(metadata.get('epoch')) is bool):
        problems.append('name-version-release-epoch-binding-unknown')
    else:
        evr = version + '-' + release
        purl = artifact.get('purl')
        if (artifact.get('version') != evr or not isinstance(purl, str)
                or not re.fullmatch(r'pkg:rpm/(?:bluefin|fedora)/' + re.escape(name) + r'@[^?]+(?:\?.*)?', purl)
                or unquote(purl.split('@', 1)[1].split('?', 1)[0]) != evr):
            problems.append('catalog-version-purl-binding-unknown')
        family = 'curl' if name in {'curl', 'libcurl', 'libcurl-minimal'} else 'httpd'
        if metadata.get('sourceRpm') != family + '-' + evr + '.src.rpm':
            problems.append('owning-source-rpm-binding-unknown')
    signatures = metadata.get('signatures')
    if (not isinstance(signatures, list) or not 1 <= len(signatures) <= 8
            or any(not isinstance(s, dict) or s.get('algo') != 'RSA' or s.get('hash') != 'SHA256'
                   or not isinstance(s.get('issuer'), str) or not re.fullmatch(r'[0-9a-f]{16}', s['issuer'])
                   for s in signatures)):
        problems.append('stored-rpm-signature-metadata-unknown')
    if metadata.get('architecture') not in ('x86_64', 'noarch') or metadata.get('vendor') != 'Fedora Project':
        problems.append('publisher-platform-metadata-unknown')
    if artifact.get('metadataType') != 'rpm-db-entry':
        problems.append('native-rpm-metadata-type-unknown')
    return identity, problems


def collect(rootfs, sbom, image, sbom_sha256):
    rootfs = os.fspath(rootfs)
    if not IMAGE.fullmatch(image) or not SHA256.fullmatch(sbom_sha256):
        raise ValueError('Require immutable Finite image and raw native SBOM hash')
    if (not isinstance(sbom, dict) or sbom.get('source', {}).get('type') != 'directory'
            or sbom.get('source', {}).get('metadata', {}).get('path') != rootfs):
        raise ValueError('Native SBOM directory source must equal the caller extracted rootfs')
    artifacts = sbom.get('artifacts')
    if not isinstance(artifacts, list) or len(artifacts) > 100000:
        raise ValueError('Native artifact inventory is invalid or unbounded')
    selected, seen_ids, seen_components = [], set(), set()
    regular_count = total_size = rows = 0
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValueError('Invalid native artifact record')
        if (artifact.get('name') not in TARGETS or artifact.get('type') != 'rpm'
                or artifact.get('foundBy') != 'rpm-db-cataloger'):
            continue
        if len(selected) >= len(TARGETS):
            raise ValueError('Ambiguous or excessive target RPM inventory')
        if (not isinstance(artifact.get('id'), str) or not artifact['id']
                or artifact['id'] in seen_ids or artifact.get('purl') in seen_components):
            raise ValueError('Duplicate/ambiguous target RPM identity')
        seen_ids.add(artifact['id'])
        seen_components.add(artifact.get('purl'))
        identity, problems = package_identity(artifact)
        files = artifact['metadata'].get('files')
        if not isinstance(files, list):
            raise ValueError('Target RPM lacks declared file manifest')
        rows += len(files)
        if rows > MAX_MANIFEST_ROWS:
            raise ValueError('Target RPM manifest exceeds metadata row bound')
        paths = set()
        for item in files:
            if not isinstance(item, dict):
                raise ValueError('Malformed declared RPM file record')
            path = declared_path(item, rootfs)
            if path and path in paths:
                raise ValueError('Duplicate declared target RPM path')
            paths.add(path)
            if type(item.get('mode')) is int and stat.S_ISREG(item['mode']):
                regular_count += 1
                if type(item.get('size')) is int and 0 <= item['size'] <= MAX_FILE:
                    total_size += item['size']
        selected.append((artifact, identity, problems, files))
    if regular_count > MAX_FILES or total_size > MAX_TOTAL_BYTES:
        raise ValueError('Selected regular files exceed count or aggregate byte bound')
    root_fd = root_descriptor(rootfs)
    packages = []
    try:
        before_root = os.fstat(root_fd)
        for artifact, identity, problems, files in selected:
            observations = []
            for item in files:
                path = declared_path(item, rootfs)
                if path is None:
                    observations.append({'path': item.get('path'), 'status': 'unknown',
                        'reason': 'noncanonical-declared-path', 'actualFileIntegrityVerified': False})
                else:
                    observations.append(observe(root_fd, path, item))
            packages.append({'rpm': identity, 'metadataStatus': 'catalog-binding-recorded' if not problems else 'unknown',
                'metadataUnknowns': problems, 'metadataSource': 'native-rpm-db-cataloger; caller-sbom-hash-bound',
                'rpmSignatureCryptographicallyVerified': False,
                'expectedFileManifestSha256': hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                'expectedFileManifestCount': len(files), 'files': observations,
                'regularFilesMatched': sum(f['actualFileIntegrityVerified'] for f in observations),
                'allDeclaredFilesIntegrityVerified': bool(observations) and all(f['actualFileIntegrityVerified'] for f in observations)})
        check = root_descriptor(rootfs)
        try:
            if (before_root.st_dev, before_root.st_ino) != (os.fstat(check).st_dev, os.fstat(check).st_ino):
                raise ValueError('Caller rootfs path changed during collection')
        finally:
            os.close(check)
    finally:
        os.close(root_fd)
    counts = Counter(f['reason'] for p in packages for f in p['files'])
    return {'schema': 1, 'status': 'diagnostic-complete-with-unknowns', 'image': image,
        'sourcePath': rootfs, 'sourceType': 'caller-authenticated-extracted-image',
        'sbomSha256': sbom_sha256, 'observedAt': datetime.now(timezone.utc).isoformat(),
        'collectorSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'targets': sorted(TARGETS), 'targetRpmPackages': packages,
        'targetsNotCataloged': sorted(TARGETS - {p['rpm']['name'] for p in packages}),
        'reasonCounts': dict(sorted(counts.items())), 'releaseEligible': False,
        'dispositionsGranted': [], 'absenceNotProof': True, 'vulnerabilityClearance': 'not-assessed',
        'limits': ['Caller must independently authenticate immutable image and retain extraction provenance; CLI image argument is a binding claim, not signature verification.',
                   'Expected RPM digests/source/signatures are catalog metadata, not a new cryptographic RPM signature check.',
                   'Byte matches cover only each recorded regular file; configs, ghost/nonregular/missing/unsafe files and mismatches remain explicit unknown.',
                   'Missing target packages and matched files do not prove module/function absence, exploit nonapplicability or source fix inclusion.',
                   'No source/backport disposition or boot/release eligibility is granted.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs', type=Path, required=True)
    parser.add_argument('--sbom', type=Path, required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite':
        parser.error('RPM byte collection requires the hosted Finite runner')
    try:
        sbom, raw_hash = read_sbom(args.sbom)
        report = collect(args.rootfs, sbom, args.image, raw_hash)
        encoded = json.dumps(report, indent=2) + '\n'
        if len(encoded.encode()) > MAX_OUTPUT:
            raise ValueError('RPM byte report exceeds compact output bound')
        with args.output.open('x') as output:
            output.write(encoded)
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
