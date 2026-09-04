# synchronization-map: section=media-routing; role=amazon-drm-handler; boundaries=utility-middleware; doc=docs/SYNCHRONIZATION_MAP.md
"""
Amazon Prime Video Widevine DRM Integration for 4K UHD Chromecast Streaming

This module handles the full authentication and playback pipeline required to
stream Amazon Prime Video content at 4K UHD on a Chromecast device.
The pipeline involves several stages:
1. Authentication to get basic access and refresh tokens.
2. Fetching the primary profile ID.
3. Obtaining a device-specific actor token using the profile and refresh token.
4. Retrieving a playback envelope for the specific title.
5. Requesting playback resources to obtain the manifest (MPD) URL.
6. Acting as a license proxy to handle Widevine DRM challenges.

WARNING: This module's implementation is highly brittle and relies on exact API
payload structures, specifically to coerce Amazon into serving TV-quality 4K
streams to a Chromecast. Modifications should be made with extreme care.
"""
import urllib.request
import urllib.parse
import urllib.error
import json
import base64
import logging
import xml.etree.ElementTree as ET
from .amazon import get_saved_auth, DEVICE_ID, DEVICE_TYPE_ID
from .opensubtitles import language3
from .subtitles_remote import LANGUAGE_NAMES

logger = logging.getLogger("castcast.amazon_drm")

HOST_ATVPS = "https://atv-ps.amazon.com"
HOST_API = "https://api.amazon.com"

def _do_get(url, headers):
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        print(f"GET {url} failed: {e.code}")
        raise

def _do_post(url, payload, headers):
    try:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        print(f"POST {url} failed: {e.code}")
        raise

def get_primary_profile(access_token):
    query = urllib.parse.urlencode({"deviceTypeID": DEVICE_TYPE_ID, "deviceID": DEVICE_ID})
    url = f"{HOST_ATVPS}/lrcedge/getDataByJavaTransform/v1/lr/profiles/profileSelection?{query}"
    res = _do_get(url, {"Authorization": f"Bearer {access_token}"})
    
    profiles = res.get("resource", {}).get("profiles", [])
    for p in profiles:
        if p.get("isDefaultProfile"):
            return p.get("profileId")
    
    if profiles:
        return profiles[0].get("profileId")
    return None

def get_actor_token(refresh_token, profile_id):
    payload = {
        "actor_id": profile_id,
        "app_name": "AIV",
        "requested_token_type": "actor_access_token",
        "source_token_type": "refresh_token",
        "source_device_tokens": [
            {
                "device_type": DEVICE_TYPE_ID,
                "account_refresh_token": {
                    "token": refresh_token
                }
            }
        ]
    }
    res = _do_post(f"{HOST_API}/auth/token", payload, {})
    return res.get("device_tokens", [{}])[0].get("actor_access_token", {}).get("token")

def get_item_details(actor_token, title_id):
    query = urllib.parse.urlencode({
        "itemId": title_id,
        "presentationScheme": "android-tv-react",
        "deviceTypeID": DEVICE_TYPE_ID,
        "deviceID": DEVICE_ID,
        "roles": "playback-envelope-supported"
    })
    url = f"{HOST_ATVPS}/lrcedge/getDataByJavaTransform/v1/lr/detailsPage/detailsPageATF?{query}"
    res = _do_get(url, {"Authorization": f"Bearer {actor_token}"})
    
    actions = res.get("resource", {}).get("actions", [])
    if not actions:
        return None
        
    for action in actions:
        if "metadata" in action and "playbackExperienceMetadata" in action["metadata"]:
            return action["metadata"]["playbackExperienceMetadata"]["playbackEnvelope"]
    return None

def get_vod_playback_resources(actor_token, playback_envelope, title_id):
    """
    Fetch the DASH manifest (MPD) URL for 4K UHD playback.
    
    CRITICAL: The payload structure must match Amazon's strict API requirements exactly.
    
    Specific requirements for 4K streaming:
    - hdcpLevel: Must be "2.3" for 4K.
    - maxVideoResolution: Must be "2160p".
    - codecs: Requesting ["H265"] ensures the highest quality stream.
    - dynamicRangeFormats: Requesting ["HDR10"] enables HDR.
    - drmType: Must be "Widevine". Do NOT change to PlayReady; Chromecast only has Widevine.
    - deviceCapabilityFamily: Set to "LivingRoomPlayer" to trick Amazon into serving
      TV-quality streams rather than standard web streams.
      
    WARNING: Do not add H.264, VP9, or other codecs to the codecs list. Doing so will
    cause Amazon to serve a mixed-quality manifest that the Chromecast cannot properly
    decode at 4K resolution.
    
    The intraTitlePlaylist[-1] index is used to select the last (highest quality)
    playlist entry from the API response.
    """
    payload = {
        "vodPlaylistedPlaybackUrlsRequest": {
            "playbackSettingsRequest": {
                "firmware": "",
                "titleId": title_id,
            },
            "device": {
                "hdcpLevel": "2.3",
                "maxVideoResolution": "2160p",
                "streamingTechnologies": {
                    "DASH": {
                        "bitrateAdaptations": ["CVBR"],
                        "codecs": ["H265"],
                        "drmType": "Widevine",
                        "dynamicRangeFormats": ["HDR10"]
                    }
                },
                "supportedStreamingTechnologies": ["DASH"]
            }
        },
        "globalParameters": {
            "playbackEnvelope": playback_envelope,
            "deviceCapabilityFamily": "LivingRoomPlayer"
        }
    }
    
    query = urllib.parse.urlencode({"deviceTypeID": DEVICE_TYPE_ID, "deviceID": DEVICE_ID})
    url = f"{HOST_ATVPS}/playback/prs/GetVodPlaybackResources?{query}"
    
    res = _do_post(url, payload, {"Authorization": f"Bearer {actor_token}"})
    
    try:
        mpd_url = res["vodPlaylistedPlaybackUrls"]["result"]["playbackUrls"]["intraTitlePlaylist"][-1]["urls"][0]["url"]
        return mpd_url
    except KeyError:
        raise Exception(f"Amazon API did not return a manifest URL. Response: {res.get('errors', res)}")

def fetch_amazon_4k_manifest(title_id):
    """
    Main entry point for casting an Amazon URL, called from service.py.
    
    This function handles token retrieval/refresh, gets the actor token and
    playback envelope, and ultimately fetches the MPD manifest URL.
    
    Token refresh is handled automatically if the primary access_token is expired.
    
    Returns a dict containing:
    - mpd_url: The DASH manifest URL.
    - actor_token: Required for the DRM license challenge.
    - playback_envelope: Required for the DRM license challenge.
    
    NOTE: The returned actor_token and playback_envelope are stored in drm_tokens
    on the mediaserver for later use by the license proxy. All three return values
    are required for successful playback.
    """
    from .amazon import refresh_access_token
    auth = get_saved_auth()
    if not auth or "tokens" not in auth or "bearer" not in auth["tokens"]:
        raise Exception("Not authenticated with Amazon")
        
    access_token = auth["tokens"]["bearer"].get("access_token")
    refresh_token = auth["tokens"]["bearer"].get("refresh_token")
    
    if not access_token or not refresh_token:
        raise Exception("Amazon token data is corrupted")
        
    try:
        profile_id = get_primary_profile(access_token)
    except Exception as e:
        if "401" in str(e) or "400" in str(e) or "403" in str(e):
            print("Access token expired, refreshing...")
            new_access_token = refresh_access_token(refresh_token)
            if new_access_token:
                access_token = new_access_token
                profile_id = get_primary_profile(access_token)
            else:
                raise Exception("Failed to refresh access token")
        else:
            raise
            
    actor_token = get_actor_token(refresh_token, profile_id)
    envelope = get_item_details(actor_token, title_id)
    if not envelope:
        raise Exception("Failed to get playback envelope")
        
    mpd_url = get_vod_playback_resources(actor_token, envelope, title_id)
    
    return {
        "mpd_url": mpd_url,
        "actor_token": actor_token,
        "playback_envelope": envelope
    }

def fetch_widevine_license(actor_token, playback_envelope, challenge_bytes):
    """
    Acts as a Widevine license proxy for the Chromecast's CDM.
    
    This function is called by the mediaserver.py proxy when the Chromecast sends
    a DRM license challenge during playback initialization.
    
    - challenge_bytes: Raw protobuf bytes from the Chromecast CDM, which are
      base64-encoded before being sent to Amazon's DRM servers.
      
    CRITICAL: Amazon's API returns the license under different JSON keys depending
    on the API version or the specific content. This function checks `"license"`,
    `"drmLicense.license"`, and `"widevineLicense.license"`. All three MUST be
    checked. Removing any of these checks will cause a 500 error on the license
    proxy, leading to an endless license request loop on the Chromecast and
    playback failure.
    
    Returns:
        RAW BYTES (base64-decoded) of the DRM license. The mediaserver sends
        these bytes directly to the Chromecast CDM as `application/octet-stream`.
    """
    import base64
    payload = {
        "playbackEnvelope": playback_envelope,
        "licenseChallenge": base64.b64encode(challenge_bytes).decode('utf-8')
    }
    query = urllib.parse.urlencode({"deviceTypeID": DEVICE_TYPE_ID, "deviceID": DEVICE_ID})
    url = f"{HOST_ATVPS}/playback/drm-vod/GetWidevineLicense?{query}"
    
    data = json.dumps(payload).encode('utf-8')
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {actor_token}'
    }
    
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raise Exception(f"Amazon DRM Error {e.code}: {e.read().decode('utf-8')}")
        
    if "license" in res:
        return base64.b64decode(res["license"])
    elif "drmLicense" in res and "license" in res["drmLicense"]:
        return base64.b64decode(res["drmLicense"]["license"])
    elif "widevineLicense" in res and "license" in res["widevineLicense"]:
        return base64.b64decode(res["widevineLicense"]["license"])
    else:
        raise Exception(f"License not found in response: {res}")


def parse_mpd_subtitles(mpd_content: str | bytes) -> list[dict]:
    """
    Parse subtitle tracks from an Amazon Prime Video DASH MPD manifest.

    Identifies all <AdaptationSet> elements where contentType="text" or mimeType in
    ("text/vtt", "application/ttml+xml", "application/mp4").

    Guarantees:
    - All 4K video representations (height="2160") and audio tracks are completely untouched.
    - Zero disruption to delicate 4K qualifying conditions.

    Returns:
        list[dict] with track metadata:
        - track_id: Integer ID derived from id attribute or index.
        - language: lang attribute, normalized with language3.
        - mime_type: mimeType attribute or representation format.
        - role: <Role value="..."/> or "subtitle".
        - label: Formatted label including display name, e.g., "English [Amazon]" or "Spanish (SDH) [Amazon]".
        - source: "amazon"
    """
    if isinstance(mpd_content, bytes):
        try:
            mpd_content = mpd_content.decode("utf-8", "replace")
        except Exception:
            return []

    if not mpd_content or not isinstance(mpd_content, str):
        return []

    try:
        root = ET.fromstring(mpd_content)
    except Exception as e:
        logger.debug(f"DEBUG-ONLY: Failed to parse MPD XML: {e}")
        return []

    def _local_tag(tag: str) -> str:
        return tag.split("}")[-1] if "}" in tag else tag

    # Pre-scan all AdaptationSets (video, audio, text) to collect all used integer IDs
    used_ids = set()
    for elem in root.iter():
        if _local_tag(elem.tag) == "AdaptationSet":
            raw_id = elem.attrib.get("id")
            if raw_id is not None:
                try:
                    int_id = int(raw_id)
                    if int_id > 0:
                        used_ids.add(int_id)
                except (ValueError, TypeError):
                    pass

    next_id = max(used_ids) + 1 if used_ids else 1
    assigned_track_ids = set()
    tracks = []

    for elem in root.iter():
        if _local_tag(elem.tag) != "AdaptationSet":
            continue

        ct = elem.attrib.get("contentType", "").strip().lower()
        mime = elem.attrib.get("mimeType", "").strip().lower()

        # Child elements inspection
        rep_elems = [c for c in elem if _local_tag(c.tag) == "Representation"]
        rep_mimes = [c.attrib.get("mimeType", "").strip().lower() for c in rep_elems]
        rep_cts = [c.attrib.get("contentType", "").strip().lower() for c in rep_elems]

        # 4K SAFEGUARD: Explicitly discard any video or audio adaptation sets
        if ct in ("video", "audio") or any(r_ct in ("video", "audio") for r_ct in rep_cts):
            continue
        if elem.attrib.get("height") or elem.attrib.get("width"):
            continue
        if any(c.attrib.get("height") or c.attrib.get("width") for c in rep_elems):
            continue

        # Safeguard: check for media codecs that indicate audio or video
        rep_codecs = [c.attrib.get("codecs", "").lower() for c in rep_elems]
        if any(any(v_codec in code for v_codec in ("hev", "hvc", "avc", "mp4v", "vp9", "av01", "mp4a", "ec-3", "ac-3")) for code in rep_codecs):
            continue

        # Stricter subtitle detection: for application/mp4 require text ct or stpp/wvtt text codecs
        has_text_ct = ct in ("text", "subtitle") or any(rc in ("text", "subtitle") for rc in rep_cts)
        has_text_codec = any(any(c_name in c for c_name in ("stpp", "wvtt")) for c in rep_codecs)
        is_vtt_or_ttml = mime in ("text/vtt", "application/ttml+xml") or any(rm in ("text/vtt", "application/ttml+xml") for rm in rep_mimes)
        is_mp4_sub = (mime == "application/mp4" or any(rm == "application/mp4" for rm in rep_mimes)) and (has_text_ct or has_text_codec)

        is_sub = has_text_ct or is_vtt_or_ttml or is_mp4_sub
        if not is_sub:
            continue

        # Extract track_id with collision prevention
        raw_id = elem.attrib.get("id")
        tid = None
        if raw_id is not None:
            try:
                tid = int(raw_id)
            except (ValueError, TypeError):
                tid = None
        if tid is None or tid <= 0 or tid in assigned_track_ids:
            tid = next_id
            while tid in used_ids or tid in assigned_track_ids:
                tid += 1

        assigned_track_ids.add(tid)
        used_ids.add(tid)
        next_id = max(next_id, tid + 1)

        # Extract language
        raw_lang = elem.attrib.get("lang")
        if not raw_lang and rep_elems:
            for rep in rep_elems:
                if rep.attrib.get("lang"):
                    raw_lang = rep.attrib.get("lang")
                    break
        lang = language3(raw_lang or "eng")

        # Extract mime_type
        valid_sub_mimes = ("text/vtt", "application/ttml+xml", "application/mp4")
        track_mime = mime
        if not track_mime and rep_mimes:
            for rm in rep_mimes:
                if rm in valid_sub_mimes:
                    track_mime = rm
                    break
        if not track_mime:
            track_mime = "text/vtt"

        # Extract all roles and check for caption/sdh across all Role elements
        role_elems = [c for c in elem if _local_tag(c.tag) == "Role" and (c.attrib.get("value") or c.text)]
        all_role_values = [(c.attrib.get("value") or c.text or "").strip() for c in role_elems]
        role_val = all_role_values[0] if all_role_values else "subtitle"

        is_sdh = any("caption" in r.lower() or "sdh" in r.lower() for r in all_role_values)
        if not is_sdh:
            access_elems = [c for c in elem if _local_tag(c.tag) == "Accessibility"]
            for acc in access_elems:
                acc_val = (acc.attrib.get("value") or acc.text or "").lower()
                if "caption" in acc_val or "sdh" in acc_val:
                    is_sdh = True
                    break

        # Build label with display name (from LANGUAGE_NAMES) and role decoration
        lang_name = LANGUAGE_NAMES.get(lang, LANGUAGE_NAMES.get(raw_lang, lang.upper()))
        role_lower = role_val.lower()
        if is_sdh:
            role_suffix = " (SDH)"
        elif "forced" in role_lower:
            role_suffix = " (Forced)"
        elif role_lower in ("subtitle", "main", ""):
            role_suffix = ""
        else:
            role_suffix = f" ({role_val.capitalize()})"

        label = f"{lang_name}{role_suffix} [Amazon]"

        tracks.append({
            "track_id": tid,
            "language": lang,
            "mime_type": track_mime,
            "role": role_val,
            "label": label,
            "source": "amazon",
        })

    logger.debug(f"DEBUG-ONLY: parse_mpd_subtitles extracted {len(tracks)} subtitle tracks from MPD")
    return tracks

