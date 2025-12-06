import json
import time
from pathlib import Path
from SPARQLWrapper import SPARQLWrapper, JSON
import httpx

# Load registry files
BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
QUERY_CONFIG_PATH = CONFIG_DIR / "query_config.json"
ENDPOINT_CONFIG_PATH = CONFIG_DIR / "endpoints_config.json"

def load_queries():
    with open(QUERY_CONFIG_PATH) as q:
        return json.load(q)

def load_endpoints():
    with open(ENDPOINT_CONFIG_PATH) as e:
        return json.load(e)["organizations"]


# Load SPARQL file

def load_query_file(filepath):
    with open(filepath, "r") as f:
        return f.read()


# SPARQL execution

def execute_sparql(endpoint_url, query, headers=None):
    sparql = SPARQLWrapper(endpoint_url)
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)

    if headers:
        for key, value in headers.items():
            sparql.addCustomHttpHeader(key, value)

    try:
        return sparql.query().convert()
    except Exception as e:
        return {"error": str(e)}


# Run routine query

def run_routine_query(query_id):
    queries = load_queries()
    endpoints = load_endpoints()

    if query_id not in queries:
        return {"error": "Unknown query"}

    query_cfg = queries[query_id]
    query = load_query_file(query_cfg["query_file"])

    results = {}

    for org_name in query_cfg["allowed_endpoints"]:
        org = endpoints[org_name]
        url = org["endpoint_url"]

        print(f"Querying {org_name}...")

        result = execute_sparql(url, query)
        results[org_name] = result

    return results


# Example test run
if __name__ == "__main__":
    output = run_routine_query("victims_by_gender")
    print(output)
