"""GPT and device-size checks for the file-backed workstation rehearsal."""
from pathlib import Path
from uuid import UUID

SECTOR_BYTES = 512
DISK_SECTORS = 1_000_215_216
ESP = 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b'
LINUX = '0fc63daf-8483-4772-8e79-3d69d8477de4'
ROOT = '4f68bce3-e8cd-4db1-96e7-fbcaf984b709'
XBOOTLDR = 'bc13c2ff-59e6-4262-a352-b275fd6f7172'
LEGACY = {
    1: (2_048, 1_230_848, ESP),
    7: (1_230_848, 5_425_152, LINUX),
    8: (5_425_152, 1_000_214_528, LINUX),
}
XBOOTLDR_SECTORS = 4 * 1024**3 // SECTOR_BYTES
XBOOTLDR_START = LEGACY[8][1] - XBOOTLDR_SECTORS
NATIVE = {
    1: LEGACY[1],
    7: LEGACY[7],
    8: (LEGACY[8][0], XBOOTLDR_START, ROOT),
    9: (XBOOTLDR_START, LEGACY[8][1], XBOOTLDR),
}
REHEARSAL_DISK = Path('/dev/disk/by-id/virtio-FINITEMIGRATION')
BTRFS_SLACK_BYTES = 64 * 1024**2


def partition(disk, number):
    # The caller resolves only the dedicated VirtIO device, whose kernel name
    # ends in a letter. This avoids using any host disk identifier.
    return f'{disk}{number}'


def rescue_esp(dump):
    table = dump['partitiontable']
    if table['label'] != 'gpt':
        raise ValueError('Rescue medium requires a GPT')
    entry, = (item for item in table['partitions'] if item['type'].lower() == ESP)
    return entry['node'], str(UUID(entry['uuid']))


def original_table(disk):
    lines = ['label: gpt', 'unit: sectors', 'sector-size: 512']
    for number, (start, end, kind) in LEGACY.items():
        lines.append(f'{partition(disk, number)} : start={start}, size={end - start}, type={kind}')
    return '\n'.join(lines) + '\n'


def verify_table(disk, dump, layout):
    """Require every recorded partition number, boundary and GPT type."""
    table = dump['partitiontable']
    if (table['device'] != disk or table['label'] != 'gpt' or table['unit'] != 'sectors'
            or table['sectorsize'] != SECTOR_BYTES or len(table['partitions']) != len(layout)):
        raise ValueError('Unexpected rehearsal partition table or sector size')
    entries = {entry['node']: entry for entry in table['partitions']}
    result = {}
    for number, (start, end, kind) in layout.items():
        entry = entries.get(partition(disk, number))
        if (entry is None or entry['start'] != start or entry['size'] != end - start
                or entry['type'].lower() != kind):
            raise ValueError(f'Unexpected rehearsal partition {number}')
        result[number] = entry['uuid']
    return table['id'], result


def native_table(disk, dump):
    disk_id, original = verify_table(disk, dump, LEGACY)
    # Reuse the existing partition UUIDs. GRUB, fstab and the LUKS header
    # continue to refer to the same partition after its end is moved.
    lines = ['label: gpt', f'label-id: {disk_id}', 'unit: sectors', 'sector-size: 512']
    for number, (start, end, kind) in NATIVE.items():
        uuid = f', uuid={original[number]}' if number in original else ''
        lines.append(f'{partition(disk, number)} : start={start}, size={end - start}, type={kind}{uuid}')
    return '\n'.join(lines) + '\n'


def shrink_sizes(payload_offset, mapped_bytes):
    """Compute the new dm-crypt sector count and smaller Btrfs target size."""
    original_partition_size = (LEGACY[8][1] - LEGACY[8][0]) * SECTOR_BYTES
    if (payload_offset <= 0 or payload_offset % SECTOR_BYTES
            or payload_offset + mapped_bytes != original_partition_size
            or mapped_bytes <= XBOOTLDR_SECTORS * SECTOR_BYTES + BTRFS_SLACK_BYTES):
        raise ValueError('LUKS payload offset or mapped device size does not match the original partition')
    after = mapped_bytes - XBOOTLDR_SECTORS * SECTOR_BYTES
    return after // SECTOR_BYTES, after - BTRFS_SLACK_BYTES
