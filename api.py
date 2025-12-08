import os
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from jose import jwt
from passlib.context import CryptContext

from mainEngine import run_routine_query, load_queries

app = FastAPI(title="Federated Lighthouse API (Auth + SPARQL)")

# ---------- Config loading ----------

BASE_DIR = os.path.dirname(__file__)

# user_config.json is expected at: config/user_config.json
# adjust if needed
USER_CONFIG_PATH = os.path.join(BASE_DIR, "config", "user_config.json")
if not os.path.exists(USER_CONFIG_PATH):
    # fallback: local user_config.json
    fallback = os.path.join(BASE_DIR, "user_config.json")
    USER_CONFIG_PATH = fallback

try:
    with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
        USER_CONFIG = json.load(f)
except Exception:
    USER_CONFIG = {"users": [], "jwt": {}}

JWT_SECRET = USER_CONFIG.get("jwt", {}).get("secret", "CHANGE_ME")
JWT_ALGO = USER_CONFIG.get("jwt", {}).get("algo", "HS256")
JWT_EXP_MIN = USER_CONFIG.get("jwt", {}).get("expiry_minutes", 360)

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()


# ---------- Models ----------

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str
    display_name: str


class RunQueryRequest(BaseModel):
    query_id: str
    endpoints: Optional[List[str]] = None  # optional subset of endpoints


# ---------- Auth helpers ----------

def find_user(username: str) -> Optional[Dict[str, Any]]:
    for u in USER_CONFIG.get("users", []):
        if u.get("username") == username:
            return u
    return None


def verify_password(plain_password: str, stored_password: str) -> bool:
    """
    If stored_password looks like a bcrypt hash (starts with $2),
    verify via passlib. Otherwise, fall back to plaintext comparison.
    """
    if isinstance(stored_password, str) and stored_password.startswith("$2"):
        return pwd_ctx.verify(plain_password, stored_password)
    return plain_password == stored_password


def create_jwt(payload: dict, minutes: int = JWT_EXP_MIN) -> str:
    to_encode = payload.copy()
    expire = datetime.utcnow() + timedelta(minutes=minutes)
    to_encode.update({"exp": expire})
    token = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGO)
    return token


def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    token = creds.credentials
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return data


# ---------- Auth endpoints ----------

@app.get("/health")
def health():
    return {
        "status": "ok",
        "users_count": len(USER_CONFIG.get("users", [])),
        "config_path": USER_CONFIG_PATH,
    }


@app.post("/login", response_model=LoginResponse)
def login(req: LoginRequest):
    user = find_user(req.username)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    stored_password = user.get("password", "")
    if not verify_password(req.password, stored_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    payload = {
        "sub": user.get("username"),
        "username": user.get("username"),
        "role": user.get("role", "viewer"),
        "display_name": user.get("display_name", user.get("username")),
    }

    token = create_jwt(payload)

    return LoginResponse(
        access_token=token,
        username=payload["username"],
        role=payload["role"],
        display_name=payload["display_name"],
    )


@app.get("/me")
def me(current_user: Dict[str, Any] = Depends(get_current_user)):
    return current_user


# ---------- SPARQL engine endpoints ----------

@app.get("/queries")
def list_queries() -> List[Dict[str, Any]]:
    """
    Return all configured routine queries.
    (We keep this endpoint public for now – UI still enforces login.)
    """
    queries = load_queries()
    out: List[Dict[str, Any]] = []
    for qid, cfg in queries.items():
        cfg_copy = cfg.copy()
        cfg_copy["id"] = qid
        out.append(cfg_copy)
    return out


@app.post("/run_query")
def run_query(req: RunQueryRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Run a routine query by ID.
    Optionally restrict execution to a subset of endpoints.
    """
    queries = load_queries()
    if req.query_id not in queries:
        raise HTTPException(status_code=400, detail=f"Unknown query_id: {req.query_id}")

    # mainEngine supports an optional endpoints list
    try:
        results = run_routine_query(req.query_id, endpoints_to_use=req.endpoints)
    except TypeError:
        # fallback for older mainEngine versions without endpoints_to_use
        results = run_routine_query(req.query_id)

    if isinstance(results, dict) and "error" in results:
        raise HTTPException(status_code=500, detail=results["error"])

    return results
