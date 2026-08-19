import urllib.request
import urllib.parse
import json
import time

HOST_API = "https://api.amazon.com"
DEVICE_TYPE_ID = "A3REWRVYBYPKUM"  # TV Device ID from rosso
DEVICE_ID = "1234567890"  # We can generate a random string

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
    return _do_post(f"{HOST_API}/auth/register", payload)

if __name__ == '__main__':
    print("Generating code pair...")
    pair = create_code_pair()
    print(json.dumps(pair, indent=2))
