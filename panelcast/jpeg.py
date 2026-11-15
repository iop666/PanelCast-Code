"""Minimal JPEG parsing: SOF dimension extraction and SHA-256 hashing."""

import hashlib
import struct

SOI = b"\xff\xd8\xff"
EOI = b"\xff\xd9"

# SOF markers carrying frame header (width/height). DHP/JPG excluded.
SOF_MARKERS = {
    0xC0, 0xC1, 0xC2, 0xC3,
    0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB,
    0xCD, 0xCE, 0xCF,
}

# Markers without a payload length (standalone / followed by raw entropy data).
STANDALONE = {0x01} | {0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def jpeg_dimensions(data: bytes):
    """Return (width, height) from the first SOF marker, or None if absent."""
    if data[:3] != SOI:
        raise ValueError("not a JPEG (missing SOI)")
    i = 2
    n = len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker in STANDALONE:
            i += 2
            continue
        if i + 4 > n:
            break
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in SOF_MARKERS:
            if i + 9 > n:
                raise ValueError("truncated SOF segment")
            height, width = struct.unpack(">HH", data[i + 5:i + 9])
            return width, height
        i += 2 + seg_len
    raise ValueError("no SOF marker found")


def iter_jpegs(data: bytes):
    """Yield (start, end) byte ranges of JPEG images (SOI..EOI) in a stream."""
    pos = 0
    while True:
        start = data.find(SOI, pos)
        if start < 0:
            return
        end = data.find(EOI, start + 3)
        if end < 0:
            return
        yield start, end + 2
        pos = end + 2
