# synchronization-map: section=media-routing; role=content-inspector; boundaries=core-service; doc=docs/SYNCHRONIZATION_MAP.md
"""Inspects file content heuristics to determine whether content is readable text/code or binary."""

import os
from enum import Enum

class ContentType(str, Enum):
    TEXT_CODE = "TEXT_CODE"
    BINARY = "BINARY"

def inspect_file_content(path: str, sample_size: int = 4096) -> ContentType:
    if not os.path.isfile(path):
        return ContentType.BINARY

    try:
        with open(path, "rb") as f:
            sample = f.read(sample_size)
    except OSError:
        return ContentType.BINARY

    if not sample:
        return ContentType.TEXT_CODE

    # Check for NUL bytes which rarely occur in clean text/code
    if b"\x00" in sample:
        return ContentType.BINARY

    # Test UTF-8 decoding
    try:
        decoded = sample.decode("utf-8")
    except UnicodeDecodeError:
        return ContentType.BINARY

    # Ratio of printable ASCII and standard whitespace
    printable = sum(1 for c in decoded if c.isprintable() or c in "\r\n\t")
    if printable / len(decoded) >= 0.90:
        return ContentType.TEXT_CODE

    return ContentType.BINARY
