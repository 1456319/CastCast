# synchronization-map: section=media-routing; role=amazon-extraction; boundaries=utility-middleware; doc=docs/SYNCHRONIZATION_MAP.md
import urllib.request
import urllib.parse
import json
import time
import os

HOST_API = "https://api.amazon.com"
DEVICE_TYPE_ID = "A3REWRVYBYPKUM"  


def get_config_path(filename: str) -> str:
    """Resolves config path, prioritizing Termux home on Android if present."""
    termux_candidate = os.path.join("/data/data/com.termux/files/home/.config/castcast", filename)
    if os.path.exists(termux_candidate):
        return termux_candidate
    home_dir = os.environ.get("HOME")
    if home_dir and home_dir != "/data":
        user_candidate = os.path.join(home_dir, ".config/castcast", filename)
        if os.path.exists(user_candidate):
            return user_candidate
    if os.path.isdir("/data/data/com.termux/files/home"):
        return termux_candidate
    return os.path.expanduser(f"~/.config/castcast/{filename}")


DEVICE_ID_FILE = get_config_path("amazon_device_id")


def get_device_id():
    device_file = get_config_path("amazon_device_id")
    if os.path.exists(device_file):
        with open(device_file, 'r') as f:
            return f.read().strip()
    import uuid
    new_id = str(uuid.uuid4()).replace('-', '')[:16]
    os.makedirs(os.path.dirname(device_file), exist_ok=True)
    with open(device_file, 'w') as f:
        f.write(new_id)
    return new_id

DEVICE_ID = get_device_id()
  

AUTH_FILE = get_config_path("amazon_auth.json")

def _do_post(url, payload):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode('utf-8'), "status": e.code}
    except Exception as e:
        return {"error": str(e)}

def create_code_pair():
    payload = {
        "code_data": {
            "domain": "Device",
            "device_type": DEVICE_TYPE_ID,
            "device_serial": DEVICE_ID
        }
    }
    return _do_post(f"{HOST_API}/auth/create/codepair", payload)

def poll_register(public_code, private_code):
    payload = {
        "auth_data": {
            "code_pair": {
                "public_code": public_code,
                "private_code": private_code
            }
        },
        "registration_data": {
            "app_name": "AIV",
            "app_version": "9",
            "device_model": "device_model",
            "device_serial": DEVICE_ID,
            "device_type": DEVICE_TYPE_ID,
            "os_version": "Android",
            "device_name": str(int(time.time()))
        },
        "requested_token_type": ["bearer"]
    }
    res = _do_post(f"{HOST_API}/auth/register", payload)
    
    if "response" in res and "success" in res["response"]:
        os.makedirs(os.path.dirname(AUTH_FILE), exist_ok=True)
        with open(AUTH_FILE, "w") as f:
            json.dump(res["response"]["success"], f, indent=2)
            
    return res

def get_saved_auth():
    if os.path.exists(AUTH_FILE):
        with open(AUTH_FILE, "r") as f:
            return json.load(f)
    return None

def refresh_access_token(refresh_token):
    payload = {
        "app_name": "AIV",
        "requested_token_type": "access_token",
        "source_token": refresh_token,
        "source_token_type": "refresh_token"
    }
    res = _do_post(f"{HOST_API}/auth/token", payload)
    
    if "access_token" in res:
        auth = get_saved_auth()
        if auth and "tokens" in auth and "bearer" in auth["tokens"]:
            auth["tokens"]["bearer"]["access_token"] = res["access_token"]
            with open(AUTH_FILE, "w") as f:
                json.dump(auth, f, indent=2)
            return res["access_token"]
    return None
