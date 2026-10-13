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
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('extraction_smoke', ROOT / 'scripts/bluebuild/security-scan.py')
scan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scan)


def digest(raw):
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


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
        tar_raw = archive.getvalue()
        layer_raw = gzip.compress(tar_raw, mtime=0)
        # Include a Docker-only config field; adapters must preserve its bytes.
        config_raw = json.dumps({'architecture': 'amd64', 'os': 'linux',
            'rootfs': {'type': 'layers', 'diff_ids': [digest(tar_raw)]},
            'config': {'Cmd': ['/bin/false'], 'Env': ['PATH=/usr/bin:/bin']},
            'container_config': {'Cmd': ['fixture only; never execute']},
            'history': [{'created_by': 'bounded extraction fixture'}]},
            separators=(',', ':')).encode()
        manifest = {'schemaVersion': 2,
            'mediaType': 'application/vnd.docker.distribution.manifest.v2+json',
            'config': {'mediaType': 'application/vnd.docker.container.image.v1+json',
                       'digest': digest(config_raw), 'size': len(config_raw)},
            'layers': [{'mediaType': 'application/vnd.docker.image.rootfs.diff.tar.gzip',
                        'digest': digest(layer_raw), 'size': len(layer_raw)}]}
        manifest_raw = json.dumps(manifest, separators=(',', ':')).encode()
        original = {digest(raw): raw for raw in (config_raw, layer_raw, manifest_raw)}
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
        subprocess.run(['umoci', 'unpack', '--rootless', '--image', str(layout) + ':audit',
                        str(root / 'bundle')], check=True, timeout=30)
        observed = root / 'bundle/rootfs/probe-file'
        if observed.is_symlink() or observed.read_bytes() != content:
            raise ValueError('Tiny unpacked layer differs from its original bytes')
        if any((blobs / value[7:]).read_bytes() != raw for value, raw in original.items()):
            raise ValueError('Extraction mutated original configuration/layer/manifest blobs')
        pointer = json.loads((layout / 'index.json').read_text())['manifests'][0]
        return {'schema': 1, 'status': 'PASS', 'originalImageDigest': digest(manifest_raw),
                'extractionManifestDigest': pointer['digest'], 'configurationDigest': digest(config_raw),
                'layerDigest': digest(layer_raw), 'originalBytesPreserved': True,
                'imageCodeExecuted': False, 'imageBuildOrPull': False, 'releaseEligible': False}


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
