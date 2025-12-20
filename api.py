import os
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from jose import jwt
from passlib.context import CryptContext

from mainEngine import run_routine_query, load_queries, load_endpoints  

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

JWT_ALGO = USER_CONFIG.get("jwt", {}).get("algo", "HS256")
JWT_EXP_MIN = USER_CONFIG.get("jwt", {}).get("expiry_minutes", 360)
JWT_SECRET = os.getenv(USER_CONFIG.get("jwt", {}).get("secret_env", "JWT_SECRET_KEY"))
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET_KEY not set in environment")

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

SUPER_ADMIN_ROLE = "Super_Admin"
ADMIN_ROLE = "admin"
USER_ROLE = "user"

VALID_ROLES = {SUPER_ADMIN_ROLE, ADMIN_ROLE, USER_ROLE}
VALID_DASHBOARD_ACCESS = {"none", "view", "use"}


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
    dashboard_access: str  # "none" | "view" | "use"

class PublicUser(BaseModel):
    username: str
    role: str
    display_name: str
    dashboard_access: str


class UpdateUserRequest(BaseModel):
    role: Optional[str] = None                 # "admin" | "user"
    dashboard_access: Optional[str] = None     # "none" | "view" | "use"
    display_name: Optional[str] = None         # optional if you want to edit name too




class RunQueryRequest(BaseModel):
    query_id: str
    endpoints: Optional[List[str]] = None  # optional subset of endpoints


# ---------- Auth helpers ----------

def find_user(username: str) -> Optional[Dict[str, Any]]:
    for u in USER_CONFIG.get("users", []):
        if u.get("username") == username:
            return u
    return None

def normalize_role(role: Optional[str]) -> str:
    if not role:
        return USER_ROLE

    role_clean = role.strip()

    # Preserve Super Admin role case
    if role_clean == SUPER_ADMIN_ROLE:
        return SUPER_ADMIN_ROLE

    role_lower = role_clean.lower()

    if role_lower in {"developer", "dev", "administrator"}:
        return ADMIN_ROLE

    if role_lower in {ADMIN_ROLE, USER_ROLE}:
        return role_lower
    return USER_ROLE



def normalize_dashboard_access(value: Optional[str]) -> str:
    if not value:
        return "none"
    v = value.strip().lower()
    return v if v in VALID_DASHBOARD_ACCESS else "none"


def save_user_config() -> None:
    # Persist in-memory USER_CONFIG back to disk
    with open(USER_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(USER_CONFIG, f, indent=2)


def resolve_user_password(user: Dict[str, Any]) -> str:
    """
    Resolve user password from environment variable.
    """
    env_key = user.get("password_env")
    if not env_key:
        raise HTTPException(
            status_code=500,
            detail=f"password_env not defined for user '{user.get('username')}'"
        )

    password = os.getenv(env_key)
    if not password:
        raise HTTPException(
            status_code=500,
            detail=f"Environment variable '{env_key}' is not set"
        )

    return password


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


def require_admin(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    role = normalize_role(current_user.get("role"))
    if role not in {ADMIN_ROLE, SUPER_ADMIN_ROLE}:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return current_user


def get_latest_user_record(username: str) -> Optional[Dict[str, Any]]:
    # Always enforce latest role/permissions (not just JWT contents)
    return find_user(username)


def require_dashboard_use(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    username = current_user.get("username") or current_user.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    u = get_latest_user_record(username)
    if not u:
        raise HTTPException(status_code=401, detail="User not found")

    access = normalize_dashboard_access(u.get("dashboard_access"))
    if access != "use":
        raise HTTPException(status_code=403, detail="Dashboard 'use' permission required")

    # Return latest merged info
    return {
        "username": u.get("username"),
        "display_name": u.get("display_name", u.get("username")),
        "role": normalize_role(u.get("role")),
        "dashboard_access": access
    }


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

    stored_password = resolve_user_password(user)
    if not verify_password(req.password, stored_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    role = normalize_role(user.get("role"))
    dash = normalize_dashboard_access(user.get("dashboard_access"))

    payload = {
        "sub": user.get("username"),
        "username": user.get("username"),
        "role": role,
        "display_name": user.get("display_name", user.get("username")),
        "dashboard_access": dash
    }

    token = create_jwt(payload)

    return LoginResponse(
        access_token=token,
        username=payload["username"],
        role=payload["role"],
        display_name=payload["display_name"],
        dashboard_access=payload["dashboard_access"]
    )



@app.get("/me")
def me(current_user: Dict[str, Any] = Depends(get_current_user)):
    username = current_user.get("username") or current_user.get("sub")
    u = get_latest_user_record(username) if username else None
    if not u:
        raise HTTPException(status_code=401, detail="User not found")

    return {
        "username": u.get("username"),
        "display_name": u.get("display_name", u.get("username")),
        "role": normalize_role(u.get("role")),
        "dashboard_access": normalize_dashboard_access(u.get("dashboard_access"))
    }


@app.get("/users", response_model=List[PublicUser])
def list_users(_: Dict[str, Any] = Depends(require_admin)):
    out: List[PublicUser] = []
    for u in USER_CONFIG.get("users", []):
        out.append(PublicUser(
            username=u.get("username"),
            role=normalize_role(u.get("role")),
            display_name=u.get("display_name", u.get("username")),
            dashboard_access=normalize_dashboard_access(u.get("dashboard_access"))
        ))
    return out


@app.patch("/users/{username}", response_model=PublicUser)
def update_user(username: str, req: UpdateUserRequest, current_user: Dict[str, Any] = Depends(require_admin)):
    u = find_user(username)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    
    current_role = normalize_role(current_user.get("role"))
    target_role = normalize_role(u.get("role"))

    # Super Admin is immutable unless current user IS Super Admin
    if target_role == SUPER_ADMIN_ROLE and current_role != SUPER_ADMIN_ROLE:
        raise HTTPException(
            status_code=403,
            detail="Super Admin role cannot be modified"
        )
    # Only Super Admin can assign Super Admin role
    if req.role is not None:
        requested_role = normalize_role(req.role)
        if requested_role == SUPER_ADMIN_ROLE and current_role != SUPER_ADMIN_ROLE:
            raise HTTPException(
                status_code=403,
                detail="Only Super Admin can assign Super Admin role"
            )

    if req.role is not None:
        new_role = normalize_role(req.role)
        if new_role not in VALID_ROLES:
            raise HTTPException(status_code=400, detail="Invalid role")
        u["role"] = new_role

    if req.dashboard_access is not None:
        new_access = normalize_dashboard_access(req.dashboard_access)
        if new_access not in VALID_DASHBOARD_ACCESS:
            raise HTTPException(status_code=400, detail="Invalid dashboard_access")
        u["dashboard_access"] = new_access

    if req.display_name is not None:
        u["display_name"] = req.display_name

    save_user_config()

    return PublicUser(
        username=u.get("username"),
        role=normalize_role(u.get("role")),
        display_name=u.get("display_name", u.get("username")),
        dashboard_access=normalize_dashboard_access(u.get("dashboard_access"))
    )




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
def run_query(req: RunQueryRequest, current_user: Dict[str, Any] = Depends(require_dashboard_use)):
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

@app.get("/endpoints")
def list_endpoints():
    """
    Return all configured endpoints with dynamic status.
    """
    endpoints = load_endpoints()
    # convert to a list with id field, similar to /queries
    out = []
    for eid, cfg in endpoints.items():
        cfg_copy = cfg.copy()
        cfg_copy["id"] = eid
        out.append(cfg_copy)
    return out