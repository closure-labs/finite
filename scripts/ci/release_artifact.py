"""Authenticate release packet bytes against their original Actions ZIP."""
import hashlib
from pathlib import Path
import re
import resource
import stat
import subprocess
import tempfile
import zipfile

import decision_packets

MAXIMUM = 64 * 1024**3


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


def verify_archive(directory, artifact, repository='closure-labs/finite', expected_files=None):
    """Stream hashes; never extract or execute artifact product content."""
    directory = Path(directory)
    with tempfile.TemporaryFile() as archive:
        subprocess.run(['gh', 'api', f'repos/{repository}/actions/artifacts/{artifact["id"]}/zip'],
                       stdout=archive, check=True, timeout=1800,
                       preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE,
                           (artifact['size_in_bytes'], artifact['size_in_bytes'])))
        archive.seek(0, 2)
        if archive.tell() != artifact['size_in_bytes']:
            raise ValueError('Original product archive size mismatch')
        archive.seek(0)
        if 'sha256:' + hashlib.file_digest(archive, 'sha256').hexdigest() != artifact['digest']:
            raise ValueError('Original product archive digest mismatch')
        archive.seek(0)
        files, total = {}, 0
        with zipfile.ZipFile(archive) as zipped:
            for entry in zipped.infolist():
                if entry.is_dir():
                    continue
                name = decision_packets.safe_name(entry.filename)
                total += entry.file_size
                if (name in files or len(files) >= decision_packets.MAX_FILES or total > MAXIMUM
                        or entry.file_size <= 0 or entry.flag_bits & 1
                        or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)):
                    raise ValueError('Unsafe original product archive')
                with zipped.open(entry) as source:
                    remaining, digest = entry.file_size, hashlib.sha256()
                    while chunk := source.read(min(1024 * 1024, remaining + 1)):
                        remaining -= len(chunk)
                        if remaining < 0:
                            raise ValueError('Product archive expansion exceeded declaration')
                        digest.update(chunk)
                    if remaining:
                        raise ValueError('Product archive ended early')
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
