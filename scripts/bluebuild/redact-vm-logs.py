#!/usr/bin/env python3
"""Remove the ephemeral disk key from retained VM diagnostics before upload."""
from pathlib import Path
import sys
import shutil
import gzip


def redacted_chunks(stream, secret, chunk_size=65536):
    """Bound memory and redact secrets even when split across read boundaries."""
    if not secret:
        raise ValueError('Cannot redact an empty VM key')
    pending = b''
    read = getattr(stream, 'read1', stream.read)
    while chunk := read(chunk_size):
        pending += chunk
        # Emit only bytes that cannot start a still-incomplete secret.
        cutoff = max(0, len(pending) - len(secret) + 1)
        cursor = 0
        while True:
            index = pending.find(secret, cursor)
            if index < 0 or index >= cutoff:
                break
            yield pending[cursor:index]
            yield b'[REDACTED]'
            cursor = index + len(secret)
        end = max(cursor, cutoff)
        yield pending[cursor:end]
        pending = pending[end:]
    yield pending.replace(secret, b'[REDACTED]')


def redact_logs(state, secret):
    if not secret:
        raise ValueError('Cannot redact an empty VM key')
    for path in state.rglob('*'):
        if path.suffix in ('.log', '.json') and path.is_file():
            content = path.read_bytes()
            if secret in content:
                path.write_bytes(content.replace(secret, b'[REDACTED]'))


def export_logs(state, secret, destination):
    """Only sanitized diagnostics cross into the artifact tree, fail closed."""
    if destination.exists():
        raise ValueError('VM artifact destination must be empty before export')
    redact_logs(state, secret)
    diagnostics = [path for path in state.rglob('*')
                   if path.suffix in ('.log', '.json') and path.is_file()]
    # Recheck all diagnostic content before creating any uploadable output.
    # A redactor failure, including a partial failure, leaves no artifacts.
    for path in diagnostics:
        if secret in path.read_bytes():
            raise ValueError('VM diagnostics still contain the ephemeral key')
    try:
        destination.mkdir(parents=True)
        for path in diagnostics:
            target = destination / path.relative_to(state)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def snapshot_logs(state, secret, destination):
    """Checkpoint complete redacted bytes atomically; never mutate active raw logs."""
    if not secret:
        raise ValueError('Cannot redact an empty VM key')
    for path in state.rglob('*'):
        if path.suffix not in ('.log', '.json') or not path.is_file() or path.is_symlink():
            continue
        target = destination / path.relative_to(state)
        compressed = path.name == 'home-init.log'
        if compressed:
            target = target.with_suffix('.log.gz')
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + '.tmp')
        try:
            with path.open('rb') as source, temporary.open('wb') as raw:
                if compressed:
                    with gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as output:
                        for chunk in redacted_chunks(source, secret):
                            output.write(chunk)
                else:
                    for chunk in redacted_chunks(source, secret):
                        raw.write(chunk)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    operation = snapshot_logs if sys.argv[4:] == ['--snapshot'] else export_logs
    operation(Path(sys.argv[1]), Path(sys.argv[2]).read_bytes().strip(), Path(sys.argv[3]))
