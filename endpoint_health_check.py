import json
import httpx
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "endpoints_config.json"


def load_endpoints():
    with open(CONFIG_PATH) as f:
        return json.load(f)["organizations"]


def check_endpoint(name, url):
    try:
        response = httpx.get(url, timeout=5)
        return response.status_code == 200
    except:
        return False


def health_check():
    endpoints = load_endpoints()
    status = {}

    for name, cfg in endpoints.items():
        print(f"Checking {name}...")
        alive = check_endpoint(name, cfg["endpoint_url"])
        status[name] = "online" if alive else "offline"

    return status


if __name__ == "__main__":
    result = health_check()
    print(result)
