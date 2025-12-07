from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from mainEngine import run_routine_query, load_queries

app = FastAPI(title="Federated Lighthouse SPARQL Engine API")


class RunQueryRequest(BaseModel):
    query_id: str
    endpoints: Optional[List[str]] = None


@app.get("/queries")
def list_queries() -> List[Dict[str, Any]]:
    """
    Returns the list of available routine queries (without the SPARQL text).
    """
    queries = load_queries()
    result = []

    for qid, cfg in queries.items():
        # Don't expose query_file path in the API if you don't want to
        item = {
            "id": qid,
            "title": cfg.get("title"),
            "topic": cfg.get("topic"),
            "description": cfg.get("description"),
            "allowed_endpoints": cfg.get("allowed_endpoints", []),
            "visualization": cfg.get("visualization"),
        }
        result.append(item)

    return result


@app.post("/run_query")
def run_query(req: RunQueryRequest) -> Dict[str, Any]:
    """
    Runs a routine query by ID using mainEngine and returns results per endpoint.
    Optionally restricts execution to a subset of endpoints chosen by the user.
    """
    queries = load_queries()
    if req.query_id not in queries:
        raise HTTPException(status_code=400, detail=f"Unknown query_id: {req.query_id}")

    query_cfg = queries[req.query_id]

    # If the user provided an endpoint subset, use that; otherwise use the defaults
    endpoints_to_use = req.endpoints or query_cfg.get("allowed_endpoints", [])

    results = run_routine_query(req.query_id, endpoints_to_use)

    if isinstance(results, dict) and "error" in results:
        raise HTTPException(status_code=500, detail=results["error"])

    return results