import json
import httpx
import time
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
CONFIG_PATH = BASE_DIR / "config" / "endpoints_config.json"
MINIMAL_SPARQL_QUERY = "ASK { ?s ?p ?o }"


def load_endpoints():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)["organizations"]


def classify_status(ok: bool, http_status: int | None, latency: float | None, error: Exception | None):
    """
    Map raw health info to a status string.

    Semantics we want:
    - offline: cannot reach host at all (DNS failure, connection refused, timeout)
    - online: host responds (200–299, or 401/403 "protected but up")
    - degraded: host responds but slowly (> 2s) or with odd 3xx/4xx
    - error: 5xx or other serious server-side problems
    """
    # 1) Hard connection failures: no HTTP status at all
    if error is not None and http_status is None:
        # e.g. ConnectError, DNS failure, timeout before any response
        return "offline"

    # 2) 2xx responses: success (with latency-based degradation)
    if http_status is not None and 200 <= http_status < 300:
        if latency is not None and latency > 2.0:
            return "degraded"
        return "online"

    # 3) Auth errors: server is clearly up and enforcing auth
    if http_status in (401, 403):
        # You can change this to "protected" if you want a separate label,
        # but "online" is usually fine for health purposes.
        return "online"

    # 4) 5xx responses: real server-side errors
    if http_status is not None and http_status >= 500:
        return "error"

    # 5) All other cases (e.g. weird 3xx/4xx): treat as degraded
    return "degraded"


def check_endpoint(name: str, cfg: dict) -> dict:
    """
    Perform a simple HTTP GET health check on the endpoint URL.
    Understands basic auth using the same username_env/password_env convention
    used in mainEngine.py.
    Returns a dict with status, latency_ms, http_status, error (optional).
    """
    url = cfg.get("endpoint_url")
    auth_method = cfg.get("auth_method", "none")

    auth = None
    if auth_method == "basic":
        username_env = cfg.get("username_env")
        password_env = cfg.get("password_env")
        username = os.environ.get(username_env) if username_env else cfg.get("username")
        password = os.environ.get(password_env) if password_env else None
        if username and password:
            auth = (username, password)

    start = time.perf_counter()
    http_status = None
    error = None
    ok = False

    try:
        # If this is a SPARQL endpoint, send a tiny valid SPARQL query
        params = None
        headers = None
        if cfg.get("type") == "sparql":
            params = {"query": MINIMAL_SPARQL_QUERY}
            headers = {"Accept": "application/sparql-results+json"}

        resp = httpx.get(
            url,
            auth=auth,
            params=params,
            headers=headers,
            timeout=5.0,
        )
        http_status = resp.status_code
        ok = 200 <= resp.status_code < 300
    except Exception as e:
        error = e

    latency = time.perf_counter() - start
    status = classify_status(ok, http_status, latency, error)

    return {
        "status": status,
        "latency_ms": int(latency * 1000),
        "http_status": http_status,
        "error": repr(error) if error else None,
    }


def health_check():
    """
    Run health checks for all endpoints and return a dict:
        { "SORD": {"status": "...", ...}, "DPO": {...}, ... }
    """
    endpoints = load_endpoints()
    status_map: dict[str, dict] = {}

    for name, cfg in endpoints.items():
        print(f"Checking {name}...")
        status_map[name] = check_endpoint(name, cfg)

    return status_map


if __name__ == "__main__":
    result = health_check()
    print(json.dumps(result, indent=2))
