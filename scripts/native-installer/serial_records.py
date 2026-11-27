"""Write bounded receipts to the disposable VM's dedicated VirtIO port."""
import json
import os
from pathlib import Path

EVIDENCE_NAME = 'org.finite.qualification'
EVIDENCE_PORT = Path('/dev/virtio-ports') / EVIDENCE_NAME
MAX_RECORD_BYTES = 65536


def emit_record(marker, value):
    data = json.dumps({'marker': marker, 'value': value}, ensure_ascii=True, separators=(',', ':'))
    payload = data.encode('ascii') + b'\n'
    if len(payload) > MAX_RECORD_BYTES:
        raise ValueError('VM evidence record exceeds 64 KiB')
    with os.fdopen(os.open(EVIDENCE_PORT, os.O_WRONLY | os.O_NOCTTY), 'wb') as stream:
        stream.write(payload)
