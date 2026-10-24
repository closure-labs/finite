#!/usr/bin/env python3
"""Apply and verify the one reviewed diagnostic Lorax compression preset."""
import configparser
import hashlib
from pathlib import Path
import sys
import subprocess
import tempfile

SETTINGS = {'type': 'zstd', 'args': '-Xcompression-level 15', 'bcj': 'off'}


def read(path):
    value = configparser.ConfigParser(interpolation=None)
    with Path(path).open() as source:
        value.read_file(source)
    return value


def validate_preset(path):
    value = read(path)
    if value.sections() != ['compression'] or dict(value['compression']) != SETTINGS:
        raise ValueError('Installer compression preset differs from the reviewed diagnostic')


def merge(target, preset):
    validate_preset(preset)
    value = read(target)
    if not value.has_section('compression'):
        value.add_section('compression')
    value['compression'].update(SETTINGS)
    with Path(target).open('w') as output:
        value.write(output)


def verify(target):
    value = read(target)
    if not value.has_section('compression') or any(value['compression'].get(k) != v for k, v in SETTINGS.items()):
        raise ValueError('Installed Lorax compression differs from the diagnostic preset')
    return hashlib.sha256(Path(target).read_bytes()).hexdigest()


def probe():
    # The pinned 4.6.1 CLI predates -help-comp. Exercise the codec instead of
    # inferring support from help text or an undocumented help exit status.
    with tempfile.TemporaryDirectory(prefix='finite-zstd-probe-') as temporary:
        root = Path(temporary)
        source = root / 'input'
        source.mkdir()
        expected = b'finite installer zstd capability probe\n' * 16
        (source / 'probe').write_bytes(expected)
        image = root / 'probe.squashfs'
        subprocess.run(['mksquashfs', str(source), str(image), '-noappend',
                        '-comp', 'zstd', '-Xcompression-level', '15',
                        '-processors', '1', '-mem', '64M', '-no-progress'],
                       check=True, timeout=30, stdout=subprocess.DEVNULL)
        output = root / 'output'
        subprocess.run(['unsquashfs', '-processors', '1', '-d', str(output), str(image)],
                       check=True, timeout=30, stdout=subprocess.DEVNULL)
        if (output / 'probe').read_bytes() != expected:
            raise ValueError('Pinned installer zstd round trip changed the probe bytes')


if __name__ == '__main__':
    operation, *paths = sys.argv[1:]
    if operation == 'probe' and not paths:
        probe()
    elif operation == 'preset' and len(paths) == 1:
        validate_preset(paths[0])
    elif operation == 'merge' and len(paths) == 2:
        merge(*paths)
    elif operation == 'verify' and len(paths) == 1:
        print(verify(paths[0]))
    else:
        raise ValueError('Expected probe, preset PATH, merge TARGET PRESET or verify PATH')
