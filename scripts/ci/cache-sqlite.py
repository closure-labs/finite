#!/usr/bin/env python3
"""Bound SQLite CLI lock waits for the pinned cache action on ephemeral runners.

SQLite reads startup configuration even for a SQL argument in batch mode. Keep
this setting through post-job save; the runner removes its home after the job.
This affects the CLI only, and does not change Nix daemon/library settings.
"""
import argparse
import os
from pathlib import Path
import pwd
import re
import subprocess

TIMEOUT_MS = 15000
MAX_TIMEOUT_MS = 30000
MAX_CONFIG_BYTES = 64 * 1024
MARKER = '# Finite CI cache SQLite lock wait\n'


def configure(home, config_home=None, timeout_ms=TIMEOUT_MS):
    if type(timeout_ms) is not int or not 0 < timeout_ms <= MAX_TIMEOUT_MS:
        raise ValueError('SQLite CLI timeout must be between 1 and 30000 milliseconds')
    home = Path(home)
    config_home = Path(config_home) if config_home is not None else home / '.config'
    paths = (home / '.sqliterc', config_home / 'sqlite3/sqliterc')
    block = MARKER + '.timeout ' + str(timeout_ms) + '\n'
    prepared = []
    for path in paths:
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError('SQLite startup config must have no symlinked path')
        if path.exists():
            if not path.is_file() or path.stat().st_size > MAX_CONFIG_BYTES:
                raise ValueError('Invalid or oversized SQLite startup config')
            original = path.read_text()
            # Replace only our own previous bounded timeout; keep runner settings.
            original = re.sub(re.escape(MARKER) + r'\.timeout [0-9]+\n', '', original)
        else:
            original = ''
        prepared.append((path, original.rstrip('\n') + ('\n' if original else '') + block))
    # Validate both startup locations before changing either of them.
    for path, content in prepared:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w') as output:
            output.write(content)
    return paths


def verify(sqlite='sqlite3', timeout_ms=TIMEOUT_MS, env=None):
    # The cache action uses this same plain CLI command form, without -init.
    result = subprocess.run([sqlite, ':memory:', 'PRAGMA busy_timeout;'],
                            capture_output=True, text=True, timeout=10, check=True, env=env)
    if result.stdout.strip() != str(timeout_ms):
        raise ValueError('SQLite CLI did not load the bounded cache lock timeout')
    print('SQLite CLI cache lock timeout verified: ' + str(timeout_ms) + ' ms')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_OS') != 'Linux':
        raise ValueError('Configure cache SQLite only on an ephemeral Linux Actions runner')
    # SQLite prefers the passwd home over $HOME on Unix. Support both the legacy
    # startup file and the newer XDG location; never print existing configuration.
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    configure(home, os.environ.get('XDG_CONFIG_HOME') or None)
    verify()


if __name__ == '__main__':
    main()
