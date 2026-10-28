#!/usr/bin/env python3
"""Exercise pinned umoci against tiny byte-preserving Docker/OCI metadata."""
import argparse
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import stat
import time
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('extraction_smoke', ROOT / 'scripts/bluebuild/security-scan.py')
scan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scan)


def digest(raw):
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def snapshot(root):
    """Compare bytes, link targets, modes and rootless ownership, not temp paths."""
    result = {}
    for path in sorted(root.rglob('*')):
        info = path.lstat()
        value = {'mode': info.st_mode, 'uid': info.st_uid, 'gid': info.st_gid}
        if stat.S_ISLNK(info.st_mode):
            value['target'] = os.readlink(path)
        elif stat.S_ISREG(info.st_mode):
            value['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            value['links'] = info.st_nlink
        result[str(path.relative_to(root))] = value
    return result


def smoke():
    with tempfile.TemporaryDirectory(prefix='finite-extraction-smoke-') as temporary:
        root = Path(temporary)
        layout, evidence = root / 'layout', root / 'evidence'
        blobs = layout / 'blobs/sha256'
        blobs.mkdir(parents=True)
        evidence.mkdir()
        content = b'byte-preserved fixture\n'
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w') as tar:
            entry = tarfile.TarInfo('probe-file')
            entry.mode, entry.size, entry.mtime = 0o644, len(content), 0
            tar.addfile(entry, io.BytesIO(content))
            for name in ('removed', 'opaque/old'):
                entry = tarfile.TarInfo(name)
                entry.mode, entry.size = 0o600, len(content)
                tar.addfile(entry, io.BytesIO(content))
            entry = tarfile.TarInfo('executable')
            entry.mode, entry.size = 0o755, len(content)
            tar.addfile(entry, io.BytesIO(content))
            for name, kind in [('symlink', tarfile.SYMTYPE), ('hardlink', tarfile.LNKTYPE)]:
                entry = tarfile.TarInfo(name)
                entry.type, entry.linkname = kind, 'probe-file'
                tar.addfile(entry)
        tar_raw = archive.getvalue()
        layer_raw = gzip.compress(tar_raw, mtime=0)
        second = io.BytesIO()
        with tarfile.open(fileobj=second, mode='w') as tar:
            for name in ('.wh.removed', 'opaque/.wh..wh..opq'):
                tar.addfile(tarfile.TarInfo(name))
            entry = tarfile.TarInfo('opaque/new')
            entry.mode, entry.size = 0o644, len(content)
            tar.addfile(entry, io.BytesIO(content))
        second_tar = second.getvalue()
        second_layer = gzip.compress(second_tar, mtime=0)
        # Include a Docker-only config field; adapters must preserve its bytes.
        config_raw = json.dumps({'architecture': 'amd64', 'os': 'linux',
            'rootfs': {'type': 'layers', 'diff_ids': [digest(tar_raw), digest(second_tar)]},
            'config': {'Cmd': ['/bin/false'], 'Env': ['PATH=/usr/bin:/bin']},
            'container_config': {'Cmd': ['fixture only; never execute']},
            'history': [{'created_by': 'bounded extraction fixture'}] * 2},
            separators=(',', ':')).encode()
        manifest = {'schemaVersion': 2,
            'mediaType': 'application/vnd.docker.distribution.manifest.v2+json',
            'config': {'mediaType': 'application/vnd.docker.container.image.v1+json',
                       'digest': digest(config_raw), 'size': len(config_raw)},
            'layers': [{'mediaType': 'application/vnd.docker.image.rootfs.diff.tar.gzip',
                        'digest': digest(layer_raw), 'size': len(layer_raw)},
                       {'mediaType': 'application/vnd.docker.image.rootfs.diff.tar.gzip',
                        'digest': digest(second_layer), 'size': len(second_layer)}]}
        manifest_raw = json.dumps(manifest, separators=(',', ':')).encode()
        original = {digest(raw): raw for raw in (config_raw, layer_raw, second_layer, manifest_raw)}
        for value, raw in original.items():
            (blobs / value[7:]).write_bytes(raw)
        (layout / 'oci-layout').write_text('{"imageLayoutVersion":"1.0.0"}')
        (layout / 'index.json').write_text(json.dumps({'schemaVersion': 2, 'manifests': [{
            'mediaType': manifest['mediaType'], 'digest': digest(manifest_raw),
            'size': len(manifest_raw), 'annotations': {'org.opencontainers.image.ref.name': 'audit'}}]}))
        image = 'ghcr.io/closure-labs/finite@' + digest(manifest_raw)
        bound = scan.prepare_layout(layout, image, evidence)
        if bound['parent'].encode() != manifest_raw or bound['config'].encode() != config_raw:
            raise ValueError('Extraction changed authenticated original evidence')
        started = time.monotonic()
        subprocess.run(['umoci', 'unpack', '--rootless', '--image', str(layout) + ':audit',
                        str(root / 'bundle')], check=True, timeout=30)
        bundle_seconds = time.monotonic() - started
        started = time.monotonic()
        scan.unpack_rootfs(layout, root / 'raw/rootfs')
        raw_seconds = time.monotonic() - started
        expected = snapshot(root / 'bundle/rootfs')
        if snapshot(root / 'raw/rootfs') != expected:
            raise ValueError('Raw rootfs differs from the full runtime bundle')
        if set(expected) != {'probe-file', 'executable', 'symlink', 'hardlink', 'opaque', 'opaque/new'}:
            raise ValueError('Layer whiteout/link fixture produced unexpected paths')
        if not list((root / 'bundle').glob('*.mtree')) or list((root / 'raw').glob('*.mtree')):
            raise ValueError('Fixture did not distinguish repack metadata generation')
        observed = root / 'raw/rootfs/probe-file'
        if observed.is_symlink() or observed.read_bytes() != content:
            raise ValueError('Tiny unpacked layer differs from its original bytes')
        if any((blobs / value[7:]).read_bytes() != raw for value, raw in original.items()):
            raise ValueError('Extraction mutated original configuration/layer/manifest blobs')
        # A rootfs match alone is not enough: corrupt authenticated layer bytes
        # and validly-addressed config with a wrong DiffID must both fail closed.
        damaged = blobs / digest(layer_raw)[7:]
        damaged.write_bytes(b'corrupt layer')
        def rejects(destination):
            result = subprocess.run(['umoci', 'raw', 'unpack', '--rootless', '--image',
                                     str(layout) + ':audit', str(destination)],
                                    capture_output=True, timeout=30)
            if result.returncode == 0:
                raise ValueError('Raw extraction accepted corrupt layer integrity evidence')
        rejects(root / 'corrupt-layer')
        damaged.write_bytes(layer_raw)
        pointer = json.loads((layout / 'index.json').read_text())['manifests'][0]
        wrong_config = json.loads(config_raw)
        wrong_config['rootfs']['diff_ids'][0] = 'sha256:' + '0' * 64
        wrong_raw = json.dumps(wrong_config).encode()
        (blobs / digest(wrong_raw)[7:]).write_bytes(wrong_raw)
        wrong_manifest = json.loads((blobs / pointer['digest'][7:]).read_bytes())
        wrong_manifest['config'].update(digest=digest(wrong_raw), size=len(wrong_raw))
        wrong_manifest_raw = json.dumps(wrong_manifest).encode()
        (blobs / digest(wrong_manifest_raw)[7:]).write_bytes(wrong_manifest_raw)
        wrong_pointer = {**pointer, 'digest': digest(wrong_manifest_raw), 'size': len(wrong_manifest_raw)}
        (layout / 'index.json').write_text(json.dumps({'schemaVersion': 2, 'manifests': [wrong_pointer]}))
        rejects(root / 'wrong-diffid')

        return {'schema': 1, 'status': 'PASS', 'originalImageDigest': digest(manifest_raw),
                'extractionManifestDigest': pointer['digest'], 'configurationDigest': digest(config_raw),
                'layerDigest': digest(layer_raw), 'originalBytesPreserved': True,
                'imageCodeExecuted': False, 'imageBuildOrPull': False, 'releaseEligible': False,
                'rawRootfsParity': True, 'corruptLayerRejected': True,
                'wrongDiffIdRejected': True, 'fixtureOnly': True,
                'umociVersion': subprocess.check_output(['umoci', '--version'], text=True).strip(),
                'fixtureSeconds': {'bundle': round(bundle_seconds, 6), 'raw': round(raw_seconds, 6)},
                'limits': 'Tiny warm-cache fixture; not a production performance measurement.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite':
        parser.error('Pinned image-tool compatibility validation is hosted-only')
    report = smoke()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        stream.write(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
