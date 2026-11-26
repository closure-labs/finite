"""Write structured VM evidence in bounded serial lines."""
import json


def emit_record(marker, value):
    data = json.dumps(value, ensure_ascii=True, separators=(',', ':'))
    parts = [data[offset:offset + 256] for offset in range(0, len(data), 256)]
    if len(parts) > 256:
        raise ValueError('Serial evidence record exceeds 64 KiB')
    for index, part in enumerate(parts, start=1):
        print(f'{marker} {index}/{len(parts)} {part}', flush=True)
