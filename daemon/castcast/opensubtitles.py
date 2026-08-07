"""Small OpenSubtitles client for on-demand sideloaded Chromecast subtitles."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import struct
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from io import BytesIO
from typing import Optional

API_BASE = "https://api.opensubtitles.com/api/v1"
USER_AGENT = "castcast v0.1"


@dataclass
class SubtitleResult:
    path: str
    language: str
    url: str
    label: str
    source: str = "opensubtitles"


def language3(value: str | None, default: str = "eng") -> str:
    value = (value or default).strip().lower()
    aliases = {"en": "eng", "english": "eng", "es": "spa", "spanish": "spa", "fr": "fre",
               "fra": "fre", "french": "fre", "de": "ger", "deu": "ger", "german": "ger"}
    return aliases.get(value, value[:3] or default)


def movie_hash(path: str) -> str:
    """OpenSubtitles moviehash: file size plus first/last 64 KiB as uint64s."""
    size = os.path.getsize(path)
    h = size
    with open(path, "rb") as fh:
        chunks = [fh.read(65536)]
        if size > 65536:
            fh.seek(max(size - 65536, 0))
            chunks.append(fh.read(65536))
    for chunk in chunks:
        usable = len(chunk) - (len(chunk) % 8)
        for (value,) in struct.iter_unpack("<Q", chunk[:usable]):
            h = (h + value) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


def _request(path: str, api_key: str, *, token: str = "", data: Optional[dict] = None) -> dict:
    body = None if data is None else json.dumps(data).encode("utf-8")
    req = urllib.request.Request(f"{API_BASE}{path}", data=body)
    req.add_header("Api-Key", api_key)
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as res:  # noqa: S310 - configured HTTPS API
        return json.loads(res.read().decode("utf-8", "replace") or "{}")


def _extract_subtitle(payload: bytes, filename: str, out_path: str) -> None:
    lower = filename.lower()
    if lower.endswith(".gz"):
        payload = gzip.decompress(payload)
    elif lower.endswith(".zip") or zipfile.is_zipfile(BytesIO(payload)):
        with zipfile.ZipFile(BytesIO(payload)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith((".srt", ".vtt"))]
            if not names:
                raise RuntimeError("OpenSubtitles archive did not contain .srt or .vtt subtitles")
            payload = zf.read(names[0])
            filename = names[0]
    text = payload.decode("utf-8", "replace")
    if not filename.lower().endswith(".vtt"):
        text = srt_to_vtt(text)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)


def srt_to_vtt(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\d\d:\d\d:\d\d),(\d{3})", r"\1.\2", text)
    return "WEBVTT\n\n" + text.lstrip("\ufeff\n ")


def download_best(path: str, work_dir: str, api_key: str, *, language: str = "eng",
                  token: str = "") -> SubtitleResult:
    if not api_key:
        raise RuntimeError("OpenSubtitles API key is not configured")
    lang = language3(language)
    params = urllib.parse.urlencode({
        "moviehash": movie_hash(path),
        "languages": lang,
        "order_by": "download_count",
        "order_direction": "desc",
    })
    found = _request(f"/subtitles?{params}", api_key, token=token).get("data") or []
    if not found:
        raise RuntimeError(f"No OpenSubtitles results found for {lang}")
    attrs = found[0].get("attributes") or {}
    files = attrs.get("files") or []
    if not files:
        raise RuntimeError("OpenSubtitles result did not include downloadable files")
    file_id = files[0].get("file_id")
    dl = _request("/download", api_key, token=token, data={"file_id": file_id, "sub_format": "webvtt"})
    link = dl.get("link")
    if not link:
        raise RuntimeError("OpenSubtitles did not return a download link")
    with urllib.request.urlopen(link, timeout=30) as res:  # noqa: S310 - API-issued subtitle URL
        payload = res.read()
    os.makedirs(work_dir, exist_ok=True)
    stem = hashlib.sha1((path + lang).encode()).hexdigest()[:12]
    out_path = os.path.join(work_dir, f"{stem}.{lang}.vtt")
    _extract_subtitle(payload, dl.get("file_name") or "subtitle.vtt", out_path)
    return SubtitleResult(path=out_path, language=lang, url="", label=attrs.get("release") or lang)
