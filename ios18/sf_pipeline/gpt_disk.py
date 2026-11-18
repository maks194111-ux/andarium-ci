"""Build and verify the static GPT disk used by Andarium (no device writes)."""
import hashlib
import struct
import uuid
import zlib
from pathlib import Path

SECTOR = 512
ENTRIES = 128
ENTRY_SIZE = 128


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def align(value, multiple=4096):
    return (value + multiple - 1) // multiple * multiple


def header(current, backup, last_usable, table_lba, table_crc, disk_guid):
    data = bytearray(SECTOR)
    struct.pack_into("<8sIIIIQQQQ16sQIII", data, 0, b"EFI PART", 0x10000,
                     92, 0, 0, current, backup,
                     2 + ENTRIES * ENTRY_SIZE // SECTOR, last_usable,
                     uuid.UUID(disk_guid).bytes_le, table_lba,
                     ENTRIES, ENTRY_SIZE, table_crc)
    struct.pack_into("<I", data, 16, zlib.crc32(data[:92]))
    return data


def assemble(layout, images, destination):
    """Preserve GUIDs and the data-disk policy; resize only system partitions."""
    disk = layout["system_disk"]
    cursor = 40 * SECTOR
    table = bytearray(ENTRIES * ENTRY_SIZE)
    for index, part in enumerate(disk["partitions"]):
        source = Path(images[part["name"]])
        size = source.stat().st_size
        assert size > 0
        part.update(start_bytes=cursor, size_bytes=align(size),
                    image_bytes=size, sha256=digest(source))
        encoded_name = part["name"].encode("utf-16-le")
        assert len(encoded_name) <= 72
        struct.pack_into("<16s16sQQQ72s", table, index * ENTRY_SIZE,
                         uuid.UUID(part["type_guid"]).bytes_le,
                         uuid.UUID(part["unique_guid"]).bytes_le,
                         cursor // SECTOR,
                         (cursor + part["size_bytes"]) // SECTOR - 1,
                         0, encoded_name)
        cursor += part["size_bytes"]
    total = align(cursor + len(table) + SECTOR)
    last = total // SECTOR - 1
    backup_table = last - len(table) // SECTOR
    crc = zlib.crc32(table)
    mbr = bytearray(SECTOR)
    struct.pack_into("<B3sB3sII", mbr, 446, 0, b"\0\x02\0", 0xEE,
                     b"\xff\xff\xff", 1, min(last, 0xFFFFFFFF))
    mbr[510:] = b"\x55\xaa"
    with Path(destination).open("xb") as out:
        out.truncate(total)
        out.write(mbr)
        out.write(header(1, last, backup_table - 1, 2, crc, disk["disk_guid"]))
        out.write(table)
        for part in disk["partitions"]:
            out.seek(part["start_bytes"])
            with Path(images[part["name"]]).open("rb") as source:
                while block := source.read(4 << 20):
                    out.write(block)
        out.seek(backup_table * SECTOR)
        out.write(table)
        out.write(header(last, 1, backup_table - 1, backup_table, crc,
                         disk["disk_guid"]))
    disk.update(size_bytes=total, sha256=digest(destination))
    verify(layout, destination)


def verify(layout, path):
    disk = layout["system_disk"]
    assert Path(path).stat().st_size == disk["size_bytes"]
    assert digest(path) == disk["sha256"]
    with Path(path).open("rb") as source:
        table_bytes = None
        for lba in (1, disk["size_bytes"] // SECTOR - 1):
            source.seek(lba * SECTOR)
            block = bytearray(source.read(SECTOR))
            fields = struct.unpack_from("<8sIIIIQQQQ16sQIII", block)
            assert fields[0] == b"EFI PART" and fields[2] == 92
            # Kernarium compares canonical GPT headers byte-for-byte. The first
            # usable LBA is after the table (34), NOT the first partition (40).
            assert fields[7] == 2 + ENTRIES * ENTRY_SIZE // SECTOR
            expected_crc = fields[3]
            struct.pack_into("<I", block, 16, 0)
            assert zlib.crc32(block[:92]) == expected_crc
            assert fields[5] == lba
            source.seek(fields[10] * SECTOR)
            table = source.read(fields[11] * fields[12])
            assert zlib.crc32(table) == fields[13]
            if table_bytes is not None:
                assert table == table_bytes
            table_bytes = table
        previous_end = 0
        for i, part in enumerate(disk["partitions"]):
            entry = struct.unpack_from("<16s16sQQQ72s", table_bytes, i * ENTRY_SIZE)
            assert entry[2] * SECTOR == part["start_bytes"]
            assert (entry[3] - entry[2] + 1) * SECTOR == part["size_bytes"]
            assert entry[5].decode("utf-16-le").rstrip("\0") == part["name"]
            assert part["start_bytes"] >= previous_end
            previous_end = part["start_bytes"] + part["size_bytes"]
            source.seek(part["start_bytes"])
            remaining = part["image_bytes"]
            hashed = hashlib.sha256()
            while remaining:
                data = source.read(min(remaining, 4 << 20))
                assert data
                hashed.update(data)
                remaining -= len(data)
            assert hashed.hexdigest() == part["sha256"], part["name"]
