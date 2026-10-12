#!/usr/bin/env python3
"""Unlock a test VM through its private serial socket without logging its key."""
import argparse
from pathlib import Path
import re
import socket
import sys
import time

PROMPT = re.compile(rb'Please enter passphrase for disk [^\r\n]{1,1024}:')


def relay(connection, secret, log, marker, output):
    """Keep a redaction overlap across reads, including fragmented prompts."""
    pending = b''
    prompt_buffer = b''
    unlocked = False

    def emit(data):
        data = data.replace(secret, b'[REDACTED]')
        log.write(data)
        log.flush()
        output.write(data)
        output.flush()

    while chunk := connection.recv(4096):
        pending += chunk
        prompt_buffer = (prompt_buffer + chunk)[-8192:]
        if not unlocked and PROMPT.search(prompt_buffer):
            connection.sendall(secret + b'\r')
            marker.write_text('Unlock submitted over private serial console\n')
            unlocked = True
        # Keep complete lines so a key echoed across recv boundaries is redacted.
        # Bound memory even if a malfunctioning guest emits no newlines.
        boundary = pending.rfind(b'\n') + 1
        if not boundary and len(pending) > 16384:
            boundary = len(pending) - len(secret)
            # Do not split a secret at the chosen boundary.
            start = pending.rfind(secret, 0, boundary + len(secret))
            if start != -1 and start < boundary < start + len(secret):
                boundary = start
        if boundary:
            emit(pending[:boundary])
            pending = pending[boundary:]
    emit(pending)
    if not unlocked:
        raise RuntimeError('VM never requested its disk passphrase')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('socket')
    parser.add_argument('secret', type=Path)
    parser.add_argument('log', type=Path)
    parser.add_argument('marker', type=Path)
    args = parser.parse_args()
    secret = args.secret.read_bytes().strip()
    if not re.fullmatch(rb'[a-f0-9]{64}', secret):
        raise ValueError('Expected an ephemeral 256-bit hexadecimal VM key')
    with socket.socket(socket.AF_UNIX) as connection:
        deadline = time.monotonic() + 30
        while True:
            try:
                connection.connect(args.socket)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                if time.monotonic() >= deadline:
                    raise RuntimeError('VM serial socket did not become ready') from None
                time.sleep(0.1)
        with args.log.open('wb') as log:
            relay(connection, secret, log, args.marker, sys.stdout.buffer)


if __name__ == '__main__':
    main()
