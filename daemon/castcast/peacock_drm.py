# synchronization-map: section=media-routing; role=peacock-drm; boundaries=utility-middleware; doc=docs/SYNCHRONIZATION_MAP.md
import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict

from .peacock_auth import get_saved_peacock_auth

UUID_PATTERN = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.IGNORECASE)


def parse_peacock_slug(url_or_slug: str) -> str:
    """Extract asset slug from Peacock URL or slug path."""
    match = re.search(r"/(?:movies|tv|watch/asset/[^/]+)/([^/?#]+)", url_or_slug)
    if match:
        return match.group(1)
    return url_or_slug


def extract_variant_id(url_or_slug: str) -> str:
    """Extract variant UUID from Peacock URL or slug."""
    matches = UUID_PATTERN.findall(url_or_slug)
    if matches:
        return matches[-1]
    return url_or_slug


def fetch_peacock_manifest(variant_id: str) -> Dict[str, Any]:
    """Fetch OVP playback manifest and return manifest url, license url, and tokens."""
    auth = get_saved_peacock_auth()
    user_token = auth.get("userToken")
    if not user_token:
        raise RuntimeError("No valid Peacock auth token found")

    url = f"https://ovp.peacocktv.com/video/stream/pck/vod/{variant_id}"
    headers = {
        "X-SkyOTT-UserToken": user_token,
        "X-SkyOTT-Territory": "US",
        "X-SkyOTT-Provider": "NBCUOTT",
        "X-SkyOTT-Platform": "ANDROID",
        "Accept": "application/json",
    }

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {
                "manifest_url": data.get("manifestUrl") or data.get("streamUrl", ""),
                "license_url": data.get("licenseUrl", "https://play.ovp.peacocktv.com/auth/tokens"),
                "user_token": user_token,
                "variant_id": variant_id,
            }
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Peacock OVP playback request failed: HTTP {e.code} - {e.read().decode('utf-8', errors='ignore')}")
