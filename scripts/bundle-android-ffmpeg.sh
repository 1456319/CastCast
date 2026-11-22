#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
revision=90231cc0105aef4f76926b911535f5eb73511b86
source_url="https://raw.githubusercontent.com/hzw1199/Android-FFmpeg-Prebuilt/$revision/ffmpeg-9.0/bin"
destination=android/app/src/main/jniLibs/arm64-v8a
staging=$(mktemp -d)
trap 'rm -rf "$staging"' EXIT
fetch_binary() {
    local tool=$1 digest=$2 file="$staging/lib$1.so"
    curl --fail --silent --show-error --location --retry 2 "$source_url/$tool" -o "$file"
    printf '%s  %s\n' "$digest" "$file" | sha256sum -c -
    readelf -hW "$file" | grep -q 'Machine:.*AArch64'
    readelf -lW "$file" | awk '$1 == "LOAD" { count++; if ($NF != "0x4000") exit 1 } END { if (!count) exit 1 }'
}
fetch_binary ffmpeg 9085507b0dc32643b4d6d084a7e7d3469ef17907a7ba15c22d3997ed09c932aa
fetch_binary ffprobe d8e929fcb2b3b5a1a7c8dc234f6d98834eaf8ff2ce408a85060a470b243e0bb5
install -Dm755 "$staging/libffmpeg.so" "$destination/libffmpeg.so"
install -Dm755 "$staging/libffprobe.so" "$destination/libffprobe.so"
