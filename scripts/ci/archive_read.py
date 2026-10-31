"""Bounded immutable Actions ZIP transport. Callers authenticate native producers."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import re
import resource
import stat
import subprocess
import tempfile
import time
import zipfile

import decision_packets

MAXIMUM = 64 * 1024**3


@contextmanager
def single_archive_reader(artifact, repository, *, max_bytes, timeout):
    """Authenticate one uncached transfer with explicit caller-owned limits.

    Small resume evidence must not inherit release transport's retry or
    90-minute budget. Native producer/run/attempt checks remain with the caller.
    """
    if (not isinstance(artifact, dict)
            or type(max_bytes) is not int or not 0 < max_bytes <= MAXIMUM
            or type(timeout) is not int or not 0 < timeout <= 1800
            or type(artifact.get('size_in_bytes')) is not int
            or not 0 < artifact['size_in_bytes'] <= max_bytes
            or type(artifact.get('id')) is not int or artifact['id'] <= 0
            or not isinstance(artifact.get('digest'), str)
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', artifact['digest'])):
        raise ValueError('Invalid bounded single-transfer archive metadata or limits')
    with tempfile.TemporaryFile() as archive:
        subprocess.run(['gh', 'api', f'repos/{repository}/actions/artifacts/{artifact["id"]}/zip'],
                       stdout=archive, check=True, timeout=timeout,
                       preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (max_bytes, max_bytes)))
        authenticate(archive, artifact)
        yield archive


def download_archive(archive, artifact, repository):
    command = ['gh', 'api', f'repos/{repository}/actions/artifacts/{artifact["id"]}/zip']
    deadline = time.monotonic() + 5400
    for attempt in range(3):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Archive transport exceeded its 90-minute deadline')
        archive.seek(0)
        archive.truncate()
        print(f'Downloading authenticated archive: attempt {attempt + 1}/3', flush=True)
        try:
            subprocess.run(command, stdout=archive, stderr=subprocess.PIPE, text=True,
                           check=True, timeout=min(1800, remaining),
                           preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE,
                               (artifact['size_in_bytes'], artifact['size_in_bytes'])))
            if time.monotonic() >= deadline:
                raise TimeoutError('Archive transport exceeded its 90-minute deadline')
            return
        except subprocess.CalledProcessError as error:
            status = re.search(r'HTTP ([0-9]{3})\b', error.stderr or '')
            transient = (int(status[1]) in (408, 429, 500, 502, 503, 504) if status else
                         bool(re.search(r'(?:connection timed out|connection reset by peer|TLS handshake timeout|unexpected EOF|connection refused|Could not resolve host)',
                                        error.stderr or '', re.I)))
            if not transient or attempt == 2:
                raise
        except subprocess.TimeoutExpired:
            if attempt == 2:
                raise
        delay = 2 ** (attempt + 1)
        if time.monotonic() + delay >= deadline:
            raise TimeoutError('Archive transport exceeded its 90-minute deadline')
        time.sleep(delay)


@contextmanager
def archive_reader(artifact, repository, cached_archive=None):
    if cached_archive is None:
        with tempfile.TemporaryFile() as archive:
            download_archive(archive, artifact, repository)
            authenticate(archive, artifact)
            yield archive
        return
    path = Path(cached_archive)
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError('Links in staged archive path')
    if path.exists():
        if not path.is_file():
            raise ValueError('Staged archive is not a regular file')
        with path.open('rb') as archive:
            authenticate(archive, artifact)
            yield archive
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('x+b') as archive:
            download_archive(archive, artifact, repository)
            authenticate(archive, artifact)
            yield archive
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def authenticate(archive, artifact):
    archive.seek(0, 2)
    if archive.tell() != artifact['size_in_bytes']:
        raise ValueError('Actions archive size mismatch')
    archive.seek(0)
    if 'sha256:' + hashlib.file_digest(archive, 'sha256').hexdigest() != artifact['digest']:
        raise ValueError('Actions archive digest mismatch')
    archive.seek(0)


def members(zipped, max_files=1024, max_bytes=MAXIMUM):
    names, total = set(), 0
    for entry in zipped.infolist():
        name = decision_packets.safe_name(entry.filename.rstrip('/') if entry.is_dir() else entry.filename)
        mode = stat.S_IFMT(entry.external_attr >> 16)
        if entry.is_dir():
            if mode not in (0, stat.S_IFDIR):
                raise ValueError('Unsafe archive directory')
            continue
        total += entry.file_size
        if (name in names or len(names) >= max_files or total > max_bytes
                or mode not in (0, stat.S_IFREG) or entry.flag_bits & 1):
            raise ValueError('Unsafe Actions ZIP member')
        names.add(name)
        yield name, entry


def chunks(zipped, entry):
    with zipped.open(entry) as source:
        remaining = entry.file_size
        while chunk := source.read(min(1024 * 1024, remaining + 1)):
            remaining -= len(chunk)
            if remaining < 0:
                raise ValueError('Archive exceeds declared expansion')
            yield chunk
        if remaining:
            raise ValueError('Archive ended early')


def extract(archive, output, *, max_bytes=MAXIMUM):
    output.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as zipped:
        for name, entry in members(zipped, max_bytes=max_bytes):
            path = output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as destination:
                for chunk in chunks(zipped, entry):
                    destination.write(chunk)
