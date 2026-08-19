import urllib.request
import urllib.parse
import urllib.error
import json
import time
import os
import base64
from .amazon import get_saved_auth, DEVICE_ID, DEVICE_TYPE_ID

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
                        "drmType": "Widevine"
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
        if "401" in str(e) or "400" in str(e):
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
    else:
        raise Exception(f"License not found in response: {res}")
