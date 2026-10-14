#!/usr/bin/env python3
"""Remove the ephemeral disk key from retained VM diagnostics before upload."""
from pathlib import Path
import sys
import shutil


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
        content = path.read_bytes().replace(secret, b'[REDACTED]')
        target = destination / path.relative_to(state)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + '.tmp')
        temporary.write_bytes(content)
        temporary.replace(target)


if __name__ == '__main__':
    operation = snapshot_logs if sys.argv[4:] == ['--snapshot'] else export_logs
    operation(Path(sys.argv[1]), Path(sys.argv[2]).read_bytes().strip(), Path(sys.argv[3]))
