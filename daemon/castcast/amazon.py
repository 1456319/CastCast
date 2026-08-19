import requests
import json
import time

HOST_API = "https://api.amazon.com"
DEVICE_TYPE_ID = "A3REWRVYBYPKUM"  # TV Device ID from rosso
DEVICE_ID = "1234567890"  # We can generate a random string

def create_code_pair():
    payload = {
        "code_data": {
            "domain": "Device",
            "device_type": DEVICE_TYPE_ID,
            "device_serial": DEVICE_ID
        }
    }
    
    resp = requests.post(
        f"{HOST_API}/auth/create/codepair",
        json=payload
    )
    
    if resp.status_code != 200:
        return {"error": f"Failed to create code pair: {resp.text}"}
        
    return resp.json()

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
    
    resp = requests.post(
        f"{HOST_API}/auth/register",
        json=payload
    )
    
    if resp.status_code != 200:
        return {"error": resp.text, "status": resp.status_code}
        
    return resp.json()

if __name__ == '__main__':
    # Let's test the codepair generation
    print("Generating code pair...")
    pair = create_code_pair()
    print(json.dumps(pair, indent=2))
