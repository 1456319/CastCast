#!/usr/bin/env python3
"""Select an Android version from published release tags."""

import re
import sys


def main():
    channel, commit = sys.argv[1:]
    prefix = "prototype-v" if channel == "prototype" else "v"
    latest = 200
    existing = None
    for line in sys.stdin:
        tag, target = line.rstrip("\n").split("\t")
        match = re.fullmatch(r"(prototype-v|v)([1-9]\d*)\.(\d{2})", tag)
        if not match:
            continue
        series, major, minor = match.groups()
        code = int(major) * 100 + int(minor)
        latest = max(latest, code)
        if series == prefix and target == commit:
            existing = max(code, existing or 0)

    code = existing if existing is not None else latest + 1
    if code > 2_100_000_000:
        raise ValueError("Android versionCode limit reached")
    version = f"{code // 100}.{code % 100:02d}"
    print(f"version={version}")
    print(f"code={code}")
    print(f"tag={prefix}{version}")
    print(f"published={str(existing is not None).lower()}")


if __name__ == "__main__":
    main()
