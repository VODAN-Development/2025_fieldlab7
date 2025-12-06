from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List

from mainEngine import run_routine_query, load_queries

app = FastAPI(title="Federated Lighthouse SPARQL Engine API")


class RunQueryRequest(BaseModel):
    query_id: str


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
    """
    queries = load_queries()
    if req.query_id not in queries:
        raise HTTPException(status_code=400, detail=f"Unknown query_id: {req.query_id}")

    results = run_routine_query(req.query_id)

    # If your run_routine_query returns {"error": "..."} on failure,
    # you can standardize the error handling here if you like.
    if isinstance(results, dict) and "error" in results:
        raise HTTPException(status_code=500, detail=results["error"])

    return results
