#!/usr/bin/env python3
"""Check ARM64 ELF alignment, including Chaquopy's nested native libraries."""

import io
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile, is_zipfile


def binaries(archive, prefix=""):
    for name in archive.namelist():
        if name.endswith(".so"):
            yield prefix + name, archive.read(name)
        elif name.startswith("assets/chaquopy/") and name.endswith(".imy"):
            nested = io.BytesIO(archive.read(name))
            if is_zipfile(nested):
                with ZipFile(nested) as contents:
                    yield from binaries(contents, prefix + name + "!/")


with ZipFile(sys.argv[1]) as apk, tempfile.TemporaryDirectory() as temp:
    binary = Path(temp) / "library.so"
    libraries = dict(binaries(apk))
    expected = ("libffmpeg.so", "libffprobe.so", "_rust.so", "_cffi_backend.so")
    missing = [name for name in expected if not any(path.endswith("/" + name) or path == name for path in libraries)]
    if missing:
        raise SystemExit("Missing APK components: " + ", ".join(missing))
    failures = []
    for name, data in libraries.items():
        binary.write_bytes(data)
        headers = subprocess.check_output(["readelf", "-lW", binary], text=True)
        alignments = [int(row.split()[-1], 16) for row in headers.splitlines()
                      if row.strip().startswith("LOAD ")]
        if not alignments or min(alignments) < 16384:
            failures.append(name)

    if failures:
        raise SystemExit("APK libraries with unaligned load segments:\n" + "\n".join(failures))
    print(f"Verified {len(libraries)} APK native libraries for 16 KB ELF alignment.")
