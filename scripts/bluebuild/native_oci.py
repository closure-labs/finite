"""Deterministic OCI archive layers, preserving the source image's metadata.

Sealing edits OCI metadata directly instead of hashing a builder's mounted
filesystem view. This module never executes code from an image.
"""
import argparse
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile
import tempfile

MANIFEST = 'application/vnd.oci.image.manifest.v1+json'
CONFIG = 'application/vnd.oci.image.config.v1+json'
LAYER = 'application/vnd.oci.image.layer.v1.tar'
MAX_JSON = 16 * 1024**2


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def blob_name(descriptor):
    digest = descriptor.get('digest', '')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise ValueError('Only SHA256-addressed OCI blobs are supported')
    return 'blobs/sha256/' + digest[7:]


class Image:
    def __init__(self, path):
        self.archive = tarfile.open(path, 'r:*')
        try:
            self.members = {}
            for member in self.archive:
                name = member.name.removeprefix('./').rstrip('/')
                if member.isdir() and name in ('.', 'blobs', 'blobs/sha256'):
                    continue
                if not member.isfile() or name in self.members or not (
                        name in ('oci-layout', 'index.json') or re.fullmatch(r'blobs/sha256/[0-9a-f]{64}', name)):
                    raise ValueError('Unexpected or duplicate OCI archive member')
                self.members[name] = member
            if self.read_json('oci-layout').get('imageLayoutVersion') != '1.0.0':
                raise ValueError('Unsupported OCI layout version')
            self.index = self.read_json('index.json')
            descriptors = self.index.get('manifests', [])
            if len(descriptors) != 1 or descriptors[0].get('mediaType') != MANIFEST:
                raise ValueError('Expected one concrete OCI image manifest')
            self.manifest = self.read_descriptor(descriptors[0])
            if self.manifest.get('schemaVersion') != 2 or self.manifest.get('mediaType') != MANIFEST:
                raise ValueError('Unsupported OCI image manifest')
            if self.manifest['config'].get('mediaType') != CONFIG:
                raise ValueError('Unsupported image configuration media type')
            self.config = self.read_descriptor(self.manifest['config'])
            rootfs = self.config.get('rootfs', {})
            if rootfs.get('type') != 'layers' or len(rootfs.get('diff_ids', [])) != len(self.manifest.get('layers', [])):
                raise ValueError('OCI rootfs and layer count differ')
        except Exception:
            self.archive.close()
            raise

    def close(self):
        self.archive.close()

    def read_json(self, name):
        member = self.members[name]
        if not 0 < member.size <= MAX_JSON:
            raise ValueError('OCI JSON exceeds its bounded size')
        return json.loads(self.archive.extractfile(member).read())

    def read_descriptor(self, descriptor):
        name = blob_name(descriptor)
        member = self.members[name]
        if member.size != descriptor['size'] or member.size > MAX_JSON:
            raise ValueError('OCI descriptor size differs')
        value = self.archive.extractfile(member).read()
        if hashlib.sha256(value).hexdigest() != descriptor['digest'][7:]:
            raise ValueError('OCI metadata digest differs')
        return json.loads(value)


@dataclass(frozen=True)
class File:
    name: str
    data: bytes | Path
    mode: int = 0o644


def layer_file(path, files, existing_directories=()):
    """Write stable root-owned files without replacing existing directory metadata."""
    files = list(files)
    names = set()
    directories = set()
    for entry in files:
        name = PurePosixPath(entry.name)
        if str(name) != entry.name or name.is_absolute() or '..' in name.parts or str(name) in ('', '.'):
            raise ValueError('Layer file must use a canonical relative path')
        if entry.name in names or not 0 <= entry.mode <= 0o777:
            raise ValueError('Duplicate file or unsupported mode in OCI layer')
        names.add(entry.name)
        directories.update(str(p) for p in name.parents if str(p) != '.')
    if names & directories:
        raise ValueError('OCI layer file is also used as a directory')
    with tarfile.open(path, 'w', format=tarfile.PAX_FORMAT) as archive:
        for name in sorted(directories - set(existing_directories), key=lambda value: (value.count('/'), value)):
            member = tarfile.TarInfo(name)
            member.type, member.mode = tarfile.DIRTYPE, 0o755
            archive.addfile(member)
        for entry in sorted(files, key=lambda value: value.name):
            member = tarfile.TarInfo(entry.name)
            member.mode = entry.mode
            if isinstance(entry.data, bytes):
                member.size = len(entry.data)
                archive.addfile(member, io.BytesIO(entry.data))
            else:
                if entry.data.is_symlink() or not entry.data.is_file():
                    raise ValueError('Layer inputs must be regular files')
                member.size = entry.data.stat().st_size
                with entry.data.open('rb') as stream:
                    archive.addfile(member, stream)


class DigestReader:
    def __init__(self, stream):
        self.stream, self.digest = stream, hashlib.sha256()

    def read(self, size=-1):
        value = self.stream.read(size)
        self.digest.update(value)
        return value


def extract_layout(source, directory):
    """Decode OCI transport files without restoring their outer tar ownership.

    Root filesystem ownership remains in the unchanged layer blobs. bootc's
    image proxy can therefore import this layout as an ordinary build user.
    """
    directory = Path(directory)
    directory.mkdir(mode=0o700)
    image = Image(source)
    try:
        for name, member in image.members.items():
            path = directory / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            reader = DigestReader(image.archive.extractfile(member))
            with path.open('xb') as stream:
                while block := reader.read(1024**2):
                    stream.write(block)
            if name.startswith('blobs/') and reader.digest.hexdigest() != name.rsplit('/', 1)[1]:
                raise ValueError('OCI transport blob differs from its digest')
        index = json.loads(json.dumps(image.index))
        index['manifests'][0].setdefault('annotations', {})['org.opencontainers.image.ref.name'] = 'candidate'
        (directory / 'index.json').write_bytes(encoded(index))
    finally:
        image.close()
    return f'oci:{directory}:candidate'


def descriptor(data, media_type):
    return {'mediaType': media_type, 'size': len(data), 'digest': 'sha256:' + hashlib.sha256(data).hexdigest()}


def append(source, output, files, existing_directories=()):
    """Append one deterministic OCI layer and rebind manifest/config/index."""
    source, output = Path(source), Path(output)
    if output.exists() or source.resolve() == output.resolve():
        raise ValueError('Refusing to replace a source image or completed archive')
    image = Image(source)
    try:
        with tempfile.TemporaryDirectory(prefix='oci-layer-', dir=output.parent) as directory:
            layer = Path(directory) / 'layer.tar'
            layer_file(layer, files, existing_directories=existing_directories)
            layer_hash = sha256(layer)
            layer_desc = {'mediaType': LAYER, 'size': layer.stat().st_size, 'digest': 'sha256:' + layer_hash}
            config = json.loads(json.dumps(image.config))
            config['rootfs']['diff_ids'].append(layer_desc['digest'])
            config.setdefault('history', []).append({'created': config.get('created', '1970-01-01T00:00:00Z'),
                                                    'created_by': 'Finite native image sealing'})
            config_data = encoded(config)
            config_desc = descriptor(config_data, CONFIG)
            manifest = {**image.manifest, 'config': config_desc,
                        'layers': [*image.manifest['layers'], layer_desc]}
            manifest_data = encoded(manifest)
            manifest_desc = descriptor(manifest_data, MANIFEST)
            index = {**image.index, 'manifests': [{**image.index['manifests'][0], **manifest_desc}]}
            added = {blob_name(config_desc): config_data, blob_name(manifest_desc): manifest_data,
                     'index.json': encoded(index)}
            staged = Path(directory) / 'completed.oci.tar'
            with tarfile.open(staged, 'w', format=tarfile.PAX_FORMAT) as archive:
                for name, member in sorted(image.members.items()):
                    if name == 'index.json' or name in added or name == blob_name(layer_desc):
                        continue
                    reader = DigestReader(image.archive.extractfile(member))
                    archive.addfile(member, reader)
                    if name.startswith('blobs/') and reader.digest.hexdigest() != name.rsplit('/', 1)[1]:
                        raise ValueError('Source OCI blob content differs from its digest')
                for name, data in sorted(added.items()):
                    member = tarfile.TarInfo(name)
                    member.size, member.mode = len(data), 0o644
                    archive.addfile(member, io.BytesIO(data))
                member = tarfile.TarInfo(blob_name(layer_desc))
                member.size, member.mode = layer.stat().st_size, 0o644
                with layer.open('rb') as stream:
                    archive.addfile(member, stream)
            os.link(staged, output)
            return manifest_desc['digest']
    finally:
        image.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Expose a verified OCI archive as a rootless layout')
    parser.add_argument('source', type=Path)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    try:
        print(extract_layout(args.source, args.directory))
    except (OSError, ValueError, KeyError, tarfile.TarError) as error:
        parser.exit(1, f'OCI layout extraction failed: {error}\n')
