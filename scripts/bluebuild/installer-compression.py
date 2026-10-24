#!/usr/bin/env python3
"""Apply and verify the one reviewed diagnostic Lorax compression preset."""
import configparser
import hashlib
import json
from pathlib import Path
import sys

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


if __name__ == '__main__':
    operation, *paths = sys.argv[1:]
    if operation == 'preset' and len(paths) == 1:
        validate_preset(paths[0])
    elif operation == 'merge' and len(paths) == 2:
        merge(*paths)
    elif operation == 'verify' and len(paths) == 1:
        print(verify(paths[0]))
    else:
        raise ValueError('Expected preset PATH, merge TARGET PRESET or verify PATH')
