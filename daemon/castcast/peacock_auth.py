# synchronization-map: section=media-routing; role=peacock-auth; boundaries=utility-middleware; doc=docs/SYNCHRONIZATION_MAP.md
import json
import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple

AUTH_FILE_PATH = os.path.expanduser("~/.config/castcast/peacock_auth.json")


def parse_ovp_token_payload(payload_str: str) -> Tuple[str, str]:
    """Parse Peacock OVP token and expiry from JSON payload string."""
    data = json.loads(payload_str)
    token = data.get("userToken", "")
    token_expiry = data.get("tokenExpiry")
    expiry = token_expiry.get("expiryTime", "") if isinstance(token_expiry, dict) else ""
    return token, expiry


def save_peacock_auth(auth_data: dict) -> None:
    """Save Peacock authentication data to local JSON file."""
    path = Path(AUTH_FILE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(auth_data, f, indent=2)


def get_saved_peacock_auth() -> dict:
    """Load cached Peacock authentication data from local JSON file."""
    path = Path(AUTH_FILE_PATH)
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def extract_device_token(
    adb_target: Optional[str] = "192.168.1.28:5555",
    adb_device: Optional[str] = None,
) -> dict:
    """Extract live OVP user token from connected Android device if rooted."""
    target = adb_device if adb_device is not None else adb_target
    cmd = ["adb"]
    if target:
        cmd.extend(["-s", target])
    cmd.extend(["shell", "su -c 'cat /data/data/com.peacocktv.peacockandroid/files/ovpTokenFileDataSource'"])

    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode == 0 and res.stdout.strip():
        try:
            tok, exp = parse_ovp_token_payload(res.stdout.strip())
            auth = {"userToken": tok, "expiry": exp}
            save_peacock_auth(auth)
            return auth
        except Exception:
            pass
    return get_saved_peacock_auth()
