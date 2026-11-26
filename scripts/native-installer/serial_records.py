"""Write structured VM evidence in bounded serial lines."""
import base64
import json


def emit_record(marker, value):
    encoded = json.dumps(value, ensure_ascii=True, separators=(',', ':')).encode('ascii')
    data = base64.b64encode(encoded).decode('ascii')
    parts = [data[offset:offset + 256] for offset in range(0, len(data), 256)]
    if len(parts) > 256:
        raise ValueError('Encoded serial evidence record exceeds 64 KiB')
    for index, part in enumerate(parts, start=1):
        print(f'{marker} {index}/{len(parts)} {part}|END|', flush=True)
