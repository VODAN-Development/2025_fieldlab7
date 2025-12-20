import httpx
import os
import json
import time
import pandas as pd
from pathlib import Path
from typing import List, Optional
from SPARQLWrapper import SPARQLWrapper, JSON
from dotenv import load_dotenv
from endpoint_health_check import health_check


load_dotenv()

# Load registry files
BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
QUERY_CONFIG_PATH = CONFIG_DIR / "query_config.json"
ENDPOINT_CONFIG_PATH = CONFIG_DIR / "endpoints_config.json"

def load_queries():
    with open(QUERY_CONFIG_PATH) as q:
        return json.load(q)

def load_endpoints():
    
    #Load endpoint configs and overlay dynamic health status.    
    with open(ENDPOINT_CONFIG_PATH, encoding="utf-8") as e:
        orgs = json.load(e)["platforms"]

    # Try to compute live statuses; if anything goes wrong, fall back to config status
    dynamic_status = {}
    try:
        dynamic_status = health_check()
    except Exception as e:
        print(f"Warning: health_check failed, using static status from config. Error: {e}")

    for name, cfg in orgs.items():
        live = dynamic_status.get(name)
        if live and "status" in live:
            cfg["status"] = live["status"]
        else:
            # keep existing or default to 'unknown'
            cfg["status"] = cfg.get("status", "unknown")

    return orgs


# Load SPARQL file

def load_query_file(filepath):
    with open(filepath, "r") as f:
        return f.read()


# SPARQL execution

def execute_sparql(endpoint_url, query, username=None, password=None, headers=None):
    """
    Execute a SPARQL query against the given endpoint URL.
    If username/password are provided, use HTTP Basic authentication.
    """
    sparql = SPARQLWrapper(endpoint_url)
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)

    # Basic Auth if credentials are provided
    if username and password:
        sparql.setCredentials(username, password)

    if headers:
        for key, value in headers.items():
            sparql.addCustomHttpHeader(key, value)

    try:
        return sparql.query().convert()
    except Exception as e:
        return {"error": str(e)}


# Run routine query

def run_routine_query(query_id: str, endpoints_to_use: Optional[List[str]] = None):
    """
    Execute a routine query defined in query_config.json.
    If endpoints_to_use is provided, only those endpoints are queried.
    Otherwise, the default 'allowed_endpoints' list from the query config is used.
    """
    queries = load_queries()
    endpoints = load_endpoints()

    if query_id not in queries:
        return {"error": "Unknown query"}

    query_cfg = queries[query_id]
    query = load_query_file(query_cfg["query_file"])

    # Default endpoints from config
    allowed = query_cfg.get("allowed_endpoints", [])

    # If API/UI passed a subset, use that; otherwise use defaults
    target_endpoints = endpoints_to_use or allowed

    results = {}

    for org_name in target_endpoints:
        org = endpoints.get(org_name)
        if not org:
            # In case config is inconsistent or unknown id is passed
            results[org_name] = {"error": "Unknown endpoint"}
            continue

        url = org["endpoint_url"]
        auth_method = org.get("auth_method", "none")

        username = None
        password = None

        if auth_method == "basic":
            # Prefer environment variables
            username_env = org.get("username_env")
            password_env = org.get("password_env")

            username = os.environ.get(username_env) if username_env else org.get("username")
            password = os.environ.get(password_env) if password_env else None

            if not username or not password:
                msg_parts = []
                if username_env:
                    msg_parts.append(f"'{username_env}'")
                else:
                    msg_parts.append("'username' in endpoints_config.json")

                if password_env:
                    msg_parts.append(f"'{password_env}'")

                results[org_name] = {
                    "error": (
                        f"Missing credentials for endpoint {org_name}. "
                        f"Check " + " and ".join(msg_parts) + "."
                    )
                }
                continue
        
        print(f"Querying {org_name}...")

        result = execute_sparql(url, query, username=username, password=password)
        results[org_name] = result

    return results


def merge_count_results(results_dict, group_var="country"):
    """
    Merge SPARQL COUNT results from multiple endpoints.
    Expects each endpoint result to have bindings like:
        ?<group_var>  ?count
    Returns a pandas DataFrame with columns [group_var, total_count].
    """
    combined = {}

    for endpoint, result in results_dict.items():
        if not isinstance(result, dict):
            print(f"Warning: result for {endpoint} is not a dict.")
            continue

        if "error" in result:
            print(f"Warning: {endpoint} returned an error: {result['error']}")
            continue

        bindings = result.get("results", {}).get("bindings", [])
        if not bindings:
            print(f"Info: {endpoint} returned no rows.")
            continue

        for row in bindings:
            if group_var not in row or "count" not in row:
                print(f"Warning: missing '{group_var}' or 'count' in row from {endpoint}: {row}")
                continue

            key = row[group_var]["value"]
            try:
                count = int(row["count"]["value"])
            except (ValueError, KeyError):
                print(f"Warning: bad count value in row from {endpoint}: {row}")
                continue

            combined[key] = combined.get(key, 0) + count

    # Always return a DataFrame with expected columns, even if empty
    df = pd.DataFrame(
        [{"country": k, "total_count": v} for k, v in combined.items()],
        columns=["country", "total_count"]
    )

    return df


# Example test run
if __name__ == "__main__":
    '''output = run_routine_query("victims_by_gender")
    print(output)'''

    print("Testing multi-endpoint mock query...")
    output = run_routine_query("FLmock_incidents_by_country")
    print(json.dumps(output, indent=2))
