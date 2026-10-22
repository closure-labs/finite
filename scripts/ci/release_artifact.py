"""Authenticate release packet bytes against their original Actions ZIP."""
import hashlib
from pathlib import Path
import re
import zipfile

import decision_packets
from archive_read import MAXIMUM, archive_reader, chunks, members


def bound_artifact(repository, run_id, attempt, revision, collection):
    expected = f'release-set-packet-{run_id}-{attempt}'
    artifacts = collection(f'repos/{repository}/actions/runs/{run_id}/artifacts', 'artifacts')
    matches = [item for item in artifacts if item.get('name') == expected and item.get('expired') is False]
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous original release product artifact')
    artifact = matches[0]
    binding = artifact.get('workflow_run', {})
    if (type(artifact.get('id')) is not int or artifact['id'] <= 0
            or type(artifact.get('size_in_bytes')) is not int or not 0 < artifact['size_in_bytes'] <= MAXIMUM
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest', ''))
            or binding.get('id') != run_id or binding.get('head_sha') != revision):
        raise ValueError('Original release artifact lacks immutable producer binding')
    return artifact


def verify_archive(directory, artifact, repository='closure-labs/finite', expected_files=None, *, cached_archive=None):
    """Stream hashes; never extract or execute artifact product content."""
    directory = Path(directory)
    with archive_reader(artifact, repository, cached_archive) as archive:
        files = {}
        with zipfile.ZipFile(archive) as zipped:
            for name, entry in members(zipped, max_files=decision_packets.MAX_FILES):
                if entry.file_size <= 0:
                    raise ValueError('Empty original product archive member')
                digest = hashlib.sha256()
                for chunk in chunks(zipped, entry):
                    digest.update(chunk)
                files[name] = {'sha256': digest.hexdigest(), 'size': entry.file_size}
        local = {}
        for path in directory.rglob('*'):
            if path.is_symlink():
                raise ValueError('Links in release product packet')
            if path.is_dir():
                continue
            name = path.relative_to(directory).as_posix()
            if name == 'decision-packet.json':
                continue
            decision_packets.safe_name(name)
            if not path.is_file():
                raise ValueError('Nonregular product packet member')
            local[name] = {'sha256': decision_packets.file_hash(path), 'size': path.stat().st_size}
        if local != files or (expected_files is not None and files != expected_files):
            raise ValueError('Product packet differs from authenticated original Actions archive')
        return files
