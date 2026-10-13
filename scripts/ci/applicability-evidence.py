#!/usr/bin/env python3
"""Hosted byte/platform evidence for exact Go applicability review paths.

No image code executes, and no finding is cleared. The caller supplies an
already authenticated, extracted immutable image; this records that caller's
manifest binding, not a new signature check or proof of filesystem extraction.
Format reference: https://go.dev/src/debug/buildinfo/buildinfo.go
Module framing reference: https://go.dev/src/cmd/go/internal/modload/build.go
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('applicability_security', ROOT / 'scripts/bluebuild/security-policy.py')
security = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(security)
MAX_BINARY = 256 * 1024 * 1024
MAX_METADATA = 1024 * 1024
TARGETS = {'GO-2026-6604', 'GO-2026-4871', 'GO-2026-4984', 'GO-2026-6179', 'GO-2026-6180'}
MAGIC = b'\xff Go buildinf:'
START = bytes.fromhex('3077af0c9274080241e1c107e6d618e6')
END = bytes.fromhex('f932433186182072008242104116d8f2')


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate evidence JSON key')
        result[key] = value
    return result


def regular(path, limit):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Symlinked evidence paths require separate resolution proof')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
        os.close(fd)
        raise ValueError('Evidence must be a nonempty bounded regular file')
    return os.fdopen(fd, 'rb'), info


def read(path, limit=MAX_METADATA):
    stream, _ = regular(path, limit)
    with stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Evidence read exceeds its bound')
    return raw, json.loads(raw, object_pairs_hook=unique)


def region(stream, offset, length, size, limit=MAX_METADATA):
    if offset < 0 or not 0 < length <= limit or offset > size or length > size - offset:
        raise ValueError('ELF region exceeds file or metadata bounds')
    stream.seek(offset)
    raw = stream.read(length)
    if len(raw) != length:
        raise ValueError('Truncated ELF region')
    return raw


def inline_string(raw, position):
    length = 0
    for index in range(10):
        if position + index >= len(raw):
            raise ValueError('Truncated Go build-info length')
        value = raw[position + index]
        if index == 9 and value > 1:
            raise ValueError('Overflowed Go build-info length')
        length |= (value & 127) << (7 * index)
        if not value & 128:
            position += index + 1
            if length > MAX_METADATA or length > len(raw) - position:
                raise ValueError('Go build-info string exceeds section bounds')
            return raw[position:position + length], position + length
    raise ValueError('Unterminated Go build-info length')


def build_info(stream, size):
    header = region(stream, 0, 64, size)
    if (header[:7] != b'\x7fELF\x02\x01\x01' or header[7] not in (0, 3)
            or struct.unpack_from('<H', header, 16)[0] not in (2, 3)
            or struct.unpack_from('<H', header, 18)[0] != 62
            or struct.unpack_from('<I', header, 20)[0] != 1
            or struct.unpack_from('<H', header, 52)[0] != 64):
        raise ValueError('Unsupported ELF platform/header; require executable ELF64 little-endian amd64')
    offset, entry_size, count, names_index = (struct.unpack_from('<Q', header, 40)[0],
        *struct.unpack_from('<HHH', header, 58))
    if entry_size != 64 or not 1 <= count <= 4096 or not 0 < names_index < count:
        raise ValueError('Unsupported or ambiguous ELF section table')
    table = region(stream, offset, count * entry_size, size)
    sections = [struct.unpack_from('<IIQQQQIIQQ', table, index * 64) for index in range(count)]
    names_section = sections[names_index]
    if names_section[1] != 3:
        raise ValueError('Invalid ELF section-name table')
    names = region(stream, names_section[4], names_section[5], size)
    found = []
    for section in sections:
        name_offset = section[0]
        end = names.find(b'\0', name_offset)
        if name_offset >= len(names) or end < 0:
            raise ValueError('Invalid ELF section-name offset')
        if names[name_offset:end] == b'.go.buildinfo':
            found.append(section)
    if len(found) != 1:
        raise ValueError('Require exactly one .go.buildinfo section; absence is unknown')
    section = found[0]
    if section[1] != 1 or not section[2] & 2 or section[2] & 0x800 or section[3] % 16:
        raise ValueError('Unsupported Go build-info section encoding/alignment')
    program_offset = struct.unpack_from('<Q', header, 32)[0]
    program_size, program_count = struct.unpack_from('<HH', header, 54)
    if program_size != 56 or not 1 <= program_count <= 1024:
        raise ValueError('Unsupported ELF program table')
    programs = region(stream, program_offset, program_size * program_count, size)
    mapped = []
    for index in range(program_count):
        program = struct.unpack_from('<IIQQQQQQ', programs, index * 56)
        if program[0] == 1 and (program[2] > size or program[5] > size - program[2]
                or program[6] < program[5] or program[3] + program[6] >= 2**64):
            raise ValueError('Invalid load-segment file/address bounds')
        if (program[0] == 1 and program[3] <= section[3]
                and section[3] - program[3] <= program[5]
                and section[5] <= program[5] - (section[3] - program[3])):
            mapped.append(program[2] + section[3] - program[3])
    if mapped != [section[4]]:
        raise ValueError('Go build-info section lacks unambiguous matching load-segment bytes')
    raw = region(stream, section[4], section[5], size)
    positions = [p for p in range(0, len(raw) - 31, 16) if raw[p:p + 14] == MAGIC]
    if len(positions) != 1:
        raise ValueError('Missing or ambiguous aligned Go build-info header')
    position = positions[0]
    if raw[position + 14:position + 16] != b'\x08\x02':
        raise ValueError('Unsupported Go build-info flags/pointer format')
    version_raw, next_position = inline_string(raw, position + 32)
    module_raw, _ = inline_string(raw, next_position)
    version = version_raw.decode('utf-8')
    if not re.fullmatch(r'go1\.(?:1[8-9]|2[0-7])(?:\.[0-9]+|(?:rc|beta)[0-9]+)?(?:-X:nodwarf5)?', version):
        raise ValueError('Unreviewed Go build-info compiler version')
    if not module_raw.startswith(START) or not module_raw.endswith(END):
        raise ValueError('Missing exact Go module-info framing')
    lines = module_raw[16:-16].decode('utf-8').splitlines()
    if not lines or len(lines) > 8192 or not module_raw[16:-16].endswith(b'\n'):
        raise ValueError('Truncated or unbounded Go module-info lines')
    values = {}
    for key in ('GOOS', 'GOARCH'):
        if any(line.startswith(('build\t"' + key + '"=', 'build\t`' + key + '`=')) for line in lines):
            raise ValueError('Quoted platform keys require a fuller Go settings parser')
        matching = [line[len('build\t' + key + '='):] for line in lines if line.startswith('build\t' + key + '=')]
        if len(matching) != 1:
            raise ValueError('Require one exact unquoted ' + key + ' build setting')
        values[key] = matching[0]
    if values != {'GOOS': 'linux', 'GOARCH': 'amd64'}:
        raise ValueError('ELF and Go build platform are not proven linux/amd64')
    package = [line[5:] for line in lines if line.startswith('path\t')]
    if len(package) != 1 or not package[0] or any(c.isspace() for c in package[0]):
        raise ValueError('Missing or ambiguous Go main package')
    # Retain relevant positive module records. No omitted symbol/module implies
    # absence; the original module blob hash binds any later fuller analysis.
    relevant = [line for line in lines if line.startswith(('mod\t', 'dep\tgolang.org/x/mod\t', '=>\t'))]
    if sum(len(line) for line in relevant) > 65536:
        raise ValueError('Relevant module metadata exceeds compact evidence bound')
    return {'elf': {'class': 64, 'endianness': 'little', 'machine': 'EM_X86_64'},
            'goVersion': version, 'os': values['GOOS'], 'arch': values['GOARCH'],
            'mainPackage': package[0], 'relevantModuleRecords': relevant,
            'goBuildInfoSha256': hashlib.sha256(raw).hexdigest(),
            'goModuleInfoSha256': hashlib.sha256(module_raw).hexdigest(),
            'symbolCoverage': 'not-collected', 'absenceNotProof': True}


def inspect(path):
    report = {'status': 'unknown', 'absenceNotProof': True}
    try:
        stream, before = regular(path, MAX_BINARY)
        with stream:
            digest = hashlib.sha256()
            total = 0
            while chunk := stream.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_BINARY:
                    raise ValueError('Binary grew beyond the file bound')
                digest.update(chunk)
            report.update(sha256=digest.hexdigest(), size=total)
            report.update(build_info(stream, total))
            after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns) or total != before.st_size:
                raise ValueError('Binary changed while collecting evidence')
            report['status'] = 'platform-proven'
    except (OSError, ValueError, UnicodeError, struct.error) as error:
        # Partial data never constitutes a platform proof.
        report['status'] = 'unknown'
        report['error'] = str(error)
    return report


def selected_findings(ledger):
    findings = ledger.get('findings')
    if type(ledger.get('schema')) is not int or ledger['schema'] != 1 or not isinstance(findings, list) or len(findings) > 4096:
        raise ValueError('Invalid bounded applicability ledger')
    selected = []
    paths = set()
    for finding in findings:
        aliases = finding['aliases']
        if not isinstance(aliases, list) or not aliases or any(not isinstance(a, str) for a in aliases):
            raise ValueError('Invalid advisory aliases')
        if not TARGETS.intersection(aliases):
            continue
        locations = finding['locations']
        if (not isinstance(locations, list) or not locations or not isinstance(finding['component'], str)
                or any(not security.canonical_location(p) for p in locations)):
            raise ValueError('Applicability requires exact component and all canonical locations')
        selected.append({key: finding[key] for key in ('component', 'advisory', 'aliases', 'locations')})
        paths.update(locations)
    if len(paths) > 128:
        raise ValueError('Applicability selection exceeds the path bound')
    return selected, sorted(paths)


def catalog_selection(sbom, rootfs, image):
    """Select current Go files for probes; probe IDs are not vulnerability findings."""
    source = sbom.get('source', {})
    prefix = str(rootfs).rstrip('/')
    if source.get('type') != 'directory' or source.get('metadata', {}).get('path') != prefix:
        raise ValueError('Current applicability catalog differs from extracted rootfs')
    artifacts = sbom.get('artifacts')
    if not isinstance(artifacts, list) or len(artifacts) > 200000:
        raise ValueError('Invalid bounded current applicability catalog')
    findings = []
    for artifact in artifacts:
        if artifact.get('type') != 'go-module' or artifact.get('name') not in ('stdlib', 'golang.org/x/mod'):
            continue
        locations = set()
        for entry in artifact.get('locations', []):
            for field in ('path', 'accessPath', 'realPath'):
                path = entry.get(field)
                if path is None:
                    continue
                if isinstance(path, str) and path.startswith(prefix + '/'):
                    path = path[len(prefix):]
                if not security.canonical_location(path):
                    raise ValueError('Current applicability catalog has unsafe locations')
                locations.add(path)
        probes = sorted(TARGETS if artifact['name'] == 'stdlib' else {'GO-2026-6179', 'GO-2026-6180'})
        if not locations or not isinstance(artifact.get('purl'), str):
            raise ValueError('Current Go component lacks exact identity or locations')
        findings.append({'component': artifact['purl'], 'advisory': probes[0],
                         'aliases': probes, 'locations': sorted(locations)})
    return {'schema': 1, 'image': image, 'findings': findings, 'selectionType': 'current-native-catalog-probes'}


def collect(rootfs, manifest_dir, image, profile, revision, identity, ledger):
    if not security.IMAGE.fullmatch(image):
        raise ValueError('Applicability requires an immutable Finite manifest')
    rootfs = Path(rootfs)
    if (not rootfs.is_absolute() or '..' in rootfs.parts
            or any(p.is_symlink() for p in (rootfs, *rootfs.parents)) or not rootfs.is_dir()):
        raise ValueError('Caller-extracted rootfs must be an absolute nonsymlink directory')
    parent, _ = read(manifest_dir / 'image-manifest.json')
    child = read(manifest_dir / 'platform-manifest.json')[0] if (manifest_dir / 'platform-manifest.json').exists() else None
    manifests = {'parent': parent.decode('utf-8'), 'child': child.decode('utf-8') if child else None}
    platform_digest = security.manifest_binding(image, manifests)
    selected_manifest = json.loads(manifests['child'] or manifests['parent'])
    config_raw, config = read(manifest_dir / 'image-config.json')
    descriptor = selected_manifest['config']
    if (type(descriptor.get('size')) is not int or descriptor['size'] != len(config_raw)
            or descriptor.get('digest') != 'sha256:' + hashlib.sha256(config_raw).hexdigest()
            or descriptor.get('mediaType') not in ('application/vnd.oci.image.config.v1+json', 'application/vnd.docker.container.image.v1+json')):
        raise ValueError('Applicability config does not match immutable manifest')
    labels = config['config']['Labels']
    expected = {'io.finite.profile': profile, 'org.opencontainers.image.revision': revision,
                'io.finite.build-inputs': identity, 'org.opencontainers.image.source': 'https://github.com/closure-labs/finite'}
    if (profile not in security.PROFILES or not re.fullmatch(r'[0-9a-f]{40}', revision)
            or not re.fullmatch(r'v1:[0-9a-f]{64}', identity) or config.get('os') != 'linux'
            or config.get('architecture') != 'amd64' or any(labels.get(k) != v for k, v in expected.items())):
        raise ValueError('Applicability config does not match expected source/platform/profile/identity')
    findings, paths = selected_findings(ledger)
    binaries = [{'path': path, **inspect(rootfs / PurePosixPath(path).relative_to('/'))} for path in paths]
    return {'schema': 1, 'status': 'diagnostic-complete-with-unknowns' if any(b['status'] != 'platform-proven' for b in binaries) else 'diagnostic-complete',
            'image': image, 'scannedManifestDigest': platform_digest, 'profile': profile,
            'sourceRevision': revision, 'buildIdentity': identity, 'observedAt': datetime.now(timezone.utc).isoformat(),
            'configurationDigest': descriptor['digest'], 'selectionLedgerImage': ledger.get('image'),
            'selectionType': ledger.get('selectionType', 'historical-ledger-selectors'),
            'selectionFindings': findings, 'binaries': binaries, 'releaseEligible': False, 'absenceNotProof': True,
            'dispositionsGranted': [], 'vulnerabilityClearance': 'not-assessed',
            'limits': ['Caller must retain authenticated image/extraction provenance; manifest labels do not establish publisher trust.',
                       'All selected locations are attempted; missing/symlink/malformed files remain unknown.',
                       'Platform evidence supports review only; no symbol reachability or absence proof is collected.',
                       'Selection probe IDs are not observed vulnerability findings; join current native aliases/components/all locations before any disposition.',
                       'x/mod sumdb advisories also affect embedded modules; compiler defects require originating-toolchain/rebuild proof.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('rootfs', 'manifest-dir', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--ledger', type=Path)
    selection.add_argument('--sbom', type=Path)
    for name in ('image', 'profile', 'revision', 'identity'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite':
        parser.error('Applicability file collection requires the hosted Finite runner')
    try:
        if args.sbom:
            raw, sbom = read(args.sbom, 256 * MAX_METADATA)
            ledger = catalog_selection(sbom, args.rootfs, args.image)
        else:
            raw, ledger = read(args.ledger, 16 * MAX_METADATA)
        report = collect(args.rootfs, args.manifest_dir, args.image, args.profile, args.revision, args.identity, ledger)
        report['selectionLedgerSha256'] = hashlib.sha256(raw).hexdigest()
        if args.sbom:
            report['sbomSha256'] = report['selectionLedgerSha256']
        report['collectorSha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        encoded = json.dumps(report, indent=2) + '\n'
        if len(encoded.encode()) > 16 * MAX_METADATA:
            raise ValueError('Applicability report exceeds compact evidence bound')
        with args.output.open('x') as stream:
            stream.write(encoded)
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
