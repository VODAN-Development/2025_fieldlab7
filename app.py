import time
import json
import requests
import streamlit as st
import pandas as pd
import altair as alt
from pathlib import Path
from mainEngine import merge_count_results
from endpoint_health_check import health_check

# session defaults
if "user_menu_select" not in st.session_state:
    st.session_state["user_menu_select"] = "👤"

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if "token" not in st.session_state:
    st.session_state["token"] = None

if "user" not in st.session_state:
    st.session_state["user"] = None

if "status_refresh_key" not in st.session_state:
    st.session_state["status_refresh_key"] = 0

if "last_auto_refresh" not in st.session_state:
    st.session_state["last_auto_refresh"] = 0.0

if "route" not in st.session_state:
    st.session_state["route"] = "dashboard"  # "dashboard" | "settings_account" | "settings_admin"

if "settings_menu_open" not in st.session_state:
    st.session_state["settings_menu_open"] = False

if "is_transitioning" not in st.session_state:
    st.session_state["is_transitioning"] = False

if "endpoints_initialized" not in st.session_state:
    st.session_state["endpoints_initialized"] = False

if "last_topic_key" not in st.session_state:
    st.session_state["last_topic_key"] = None

if "auto_init_done_for_topic" not in st.session_state:
    st.session_state["auto_init_done_for_topic"] = False

# ---------- Configuration ----------
API_BASE = "http://127.0.0.1:8000"
BASE_DIR = Path(__file__).resolve().parent
LOGIN_URL = f"{API_BASE}/login"
QUERIES_URL = f"{API_BASE}/queries"
RUN_QUERY_URL = f"{API_BASE}/run_query"
ME_URL = f"{API_BASE}/me"
USERS_URL = f"{API_BASE}/users"


STYLES_PATH = BASE_DIR / "assets" / "styles.css"
#STYLES_PATH = Path("assets") / "styles.css"
ENDPOINTS_CONFIG_PATH = Path("config") / "endpoints_config.json"
FDP_CONFIG_PATH = Path("config") / "fdp_config.json"

ADMIN_ROLES = {"admin", "Super_Admin"}

def normalize_role_ui(role: str) -> str:
    if role == "Super_Admin":
        return "Super_Admin"
    return role.lower()

def load_css():
    if STYLES_PATH.exists():
        st.markdown(f"<style>{STYLES_PATH.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
    else:
        st.error(f"styles.css not found at: {STYLES_PATH}")


# ---------- App config ----------
st.set_page_config(page_title="Federated Lighthouse Dashboard", layout="wide")

# ---------- Auth helpers ----------
def find_token():
    return st.session_state.get("token")


def auth_headers():
    token = find_token()
    return {"Authorization": f"Bearer {token}"} if token else {}

@st.cache_data(ttl=60)
def load_fdp_configs():
    if FDP_CONFIG_PATH.exists():
        with FDP_CONFIG_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def do_login(username: str, password: str):
    try:
        r = requests.post(LOGIN_URL, json={"username": username, "password": password}, timeout=10)
        r.raise_for_status()
        data = r.json()
        st.session_state["token"] = data["access_token"]
        st.session_state["user"] = {
            "username": data["username"],
            "role": data.get("role", "user"),
            "display_name": data.get("display_name", data.get("username")),
            "dashboard_access": data.get("dashboard_access", "none")
        }
        st.session_state["logged_in"] = True
        st.session_state["route"] = "dashboard"
        start_transition()
        return True, None
    
    except requests.HTTPError as he:
        try:
            return False, he.response.json().get("detail", str(he))
        except Exception:
            return False, str(he)
    except Exception as e:
        return False, str(e)


def do_logout():
    for key in ["token", "user", "logged_in"]:
        st.session_state.pop(key, None)
    st.session_state.pop("endpoints_initialized", None)
    st.session_state["last_auto_refresh"] = 0.0
    st.session_state["status_refresh_key"] = 0
        
    start_transition()


# ---------- Data helpers ----------
@st.cache_data(ttl=60)
def fetch_queries_cached():
    try:
        headers = auth_headers()
        resp = requests.get(QUERIES_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


def fetch_queries():
    return fetch_queries_cached()

def run_query(query_id: str, endpoints: list | None = None):
    payload = {"query_id": query_id}
    if endpoints:
        payload["endpoints"] = endpoints
    headers = auth_headers()
    resp = requests.post(RUN_QUERY_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=300)
def load_platforms_static():
    """Load only static FieldLab platform endpoints info from config (fast, no network)."""
    if ENDPOINTS_CONFIG_PATH.exists():
        with ENDPOINTS_CONFIG_PATH.open("r", encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        cfg = {}
    return cfg.get("platforms", {})

@st.cache_data(ttl=60)
def load_health_status_map(_refresh_key: int):
    """Run live health checks (slow, network). Cache for 60s."""
    return health_check()


def start_transition():
    st.session_state["is_transitioning"] = True
    st.rerun()


def refresh_me():
    """Pull latest role/permissions from backend (so changes apply without relogin)."""
    try:
        r = requests.get(ME_URL, headers=auth_headers(), timeout=10)
        r.raise_for_status()
        me = r.json()
        if "user" not in st.session_state:
            st.session_state["user"] = {}
        st.session_state["user"].update(me)
        return True
    except Exception:
        return False
    

def sparql_grouped_counts_to_df(results_by_endpoint: dict, group_var: str) -> pd.DataFrame:
    """
    Convert multi-endpoint SPARQL COUNT results into a single DataFrame:
    columns: [platform, <group_var>, count]
    Expects each endpoint result bindings to include:
      ?<group_var> and ?count
    """
    rows = []

    for platform, payload in (results_by_endpoint or {}).items():
        if not isinstance(payload, dict) or "error" in payload:
            continue

        bindings = payload.get("results", {}).get("bindings", [])
        for b in bindings:
            if group_var not in b or "count" not in b:
                continue

            group_value = b[group_var].get("value")
            count_value = b["count"].get("value")

            try:
                count_int = int(count_value)
            except Exception:
                continue

            rows.append(
                {"platform": platform, group_var: group_value, "count": count_int}
            )

    return pd.DataFrame(rows)


@st.cache_data(ttl=120)
def run_fixed_topic_query_cached(query_id: str, refresh_key: int = 0):
    """
    Run a fixed topic query with caching so it doesn't re-run on every rerender.
    refresh_key lets us invalidate the cache when needed (e.g., manual refresh).
    """
    return run_query(query_id)


# ---------- UI components ----------
def top_navbar():
    user = st.session_state.get("user")
    
    # Create a 3-column layout: title | spacer | logout button
    col_title, col_spacer, col_logout = st.columns([10, 1, 1], vertical_alignment="center")

    with col_title:
        # Logo + title in a single row (logo on the left)
        logo_col, text_col = st.columns([1, 12], vertical_alignment="center")

        with logo_col:
            st.image("assets/federated_lighthouse_logo_dark.png", width=150)

        with text_col:
            st.markdown(
                "<h2 style='margin: 6px 0px;'>Federated Lighthouse Dashboard – FieldLab 7</h2>",
                unsafe_allow_html=True
            )

    # if user missing → nothing shown
    if not user:
        return

    with col_logout:
        if st.button("⏻ Logout", key="logout_btn", type="primary"):
            do_logout()


##For right side visualization
def normalize_gender(val):
    if not val:
        return "Unknown"
    v = str(val).strip().lower()
    if v in {"female", "f"}:
        return "Female"
    if v in {"male", "m"}:
        return "Male"
    return "Unknown"


def login_view():

    # Two big columns: left for logo, right for login card
    spacer_left, col_logo, col_card, spacer_right = st.columns([1, 1.1, 1.1, 1])

    # LEFT: logo, vertically centered-ish
    with col_logo:
        st.write("")  # spacer
        st.write("")
        # Use a fixed width instead of stretching to full column
        st.image(
            "assets/federated_lighthouse_logo_dark.png",
            width=360,   # try 260–340 until it feels right
        )

    # RIGHT: login "card"
    with col_card:
        st.write("")  # spacer to move card down a bit
        st.markdown(
            """
            <div class="login-card">
                <h3>Federated Lighthouse – Login</h3>
                <p>Please log in to use the dashboard.</p>
            """,
            unsafe_allow_html=True,
        )

        # The actual form lives "inside" the card div
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")

        # Close the card div
        st.markdown("</div>", unsafe_allow_html=True)

        # Handle login after the card markup, so message appears just under it
        if submitted:
            ok, err = do_login(username, password)
            if ok:
                # do_login() triggers transition + rerun
                return 
            else:
                st.error(f"Login failed: {err}")


def render_fdp_modal(platform_key: str):
    """
    Render FDP metadata for a selected PLATFORM (application) key.
    Uses the new platform-keyed fdp_config.json structure.
    """
    fdp_configs = load_fdp_configs()
    meta = fdp_configs.get(platform_key)

    @st.dialog(f"FAIR Data Point (metadata) — {platform_key}", width="large")
    def _modal():
        if not meta:
            st.warning(f"No FDP metadata found for '{platform_key}' in fdp_config.json.")
            return

        # -------- Application / Platform summary --------
        app_meta = meta.get("application", {})
        app_name = app_meta.get("name", platform_key)
        app_abbr = app_meta.get("abbreviation", platform_key)
        app_desc = app_meta.get("description", "")
        app_stored = app_meta.get("stored", "")
        app_sparql = app_meta.get("sparql_endpoint_url", "")

        st.subheader(app_name)
        st.caption(f"Platform ID: `{platform_key}`  |  Abbreviation: `{app_abbr}`")

        if app_desc:
            st.write(app_desc)

        # Small info row
        c1, c2, c3, c4 = st.columns([2, 2, 2, 4])
        with c1:
            st.metric("Catalogues", len(meta.get("catalogues", [])))
        with c2:
            st.metric("Datasets / Providers", len(meta.get("datasets", [])))
        with c3:
            st.metric("Distributions", len(meta.get("distributions", [])))
        with c4:
            themes = meta.get("themes", [])
            if themes:
                st.write("**Themes**")
                st.write(", ".join(themes))
            else:
                st.write("**Themes**")
                st.caption("Not specified")

        st.markdown("---")

        # -------- Storage & SPARQL endpoint --------
        st.subheader("Access")
        if app_stored:
            st.write(f"**Stored:** {app_stored}")
        else:
            st.caption("Stored location not specified.")

        if app_sparql:
            st.write("**SPARQL endpoint URL:**")
            st.code(app_sparql, language="text")
        else:
            st.info("SPARQL endpoint URL is not set yet for this platform (you can fill it later).")

        st.markdown("---")

        # -------- FDP support / contacts --------
        st.subheader("Support & Contacts")

        support = meta.get("fdp_support", {})
        sup_org = support.get("organization", "")
        sup_contact = support.get("contact_person", "")

        if sup_org or sup_contact:
            if sup_org:
                st.write(f"**FDP support:** {sup_org}")
            if sup_contact:
                st.write(f"**Contact person:** {sup_contact}")
        else:
            st.caption("No FDP support information provided.")

        contacts = meta.get("contacts", [])
        if contacts:
            with st.expander("Additional contacts", expanded=False):
                for c in contacts:
                    email = c.get("email", "")
                    if email:
                        st.write(f"- {email}")
                    else:
                        st.write("- (no email provided)")
        else:
            st.caption("No additional contacts listed.")

        st.markdown("---")

        # -------- Catalogues --------
        st.subheader("Catalogues")

        cats = meta.get("catalogues", [])
        if not cats:
            st.caption("No catalogues listed.")
        else:
            for cat in cats:
                title = cat.get("title", "(untitled catalogue)")
                abbr = cat.get("abbreviation", "")
                link = cat.get("link", "")

                header = title if not abbr else f"{title} ({abbr})"

                with st.expander(header, expanded=False):
                    if link:
                        st.write(f"**Catalogue link:** {link}")
                    else:
                        st.caption("Catalogue link not available.")

        st.markdown("---")

        # -------- Datasets / Data providers --------
        st.subheader("Datasets / Data Providers")

        datasets = meta.get("datasets", [])
        if not datasets:
            st.caption("No dataset providers listed.")
        else:
            for ds in datasets:
                org_name = ds.get("organization_name", ds.get("title", "(unknown provider)"))
                ds_abbr = ds.get("abbreviation", "")
                org_link = ds.get("organization_link", "")
                ds_desc = ds.get("description", "")

                header = org_name if not ds_abbr else f"{org_name} ({ds_abbr})"

                with st.expander(header, expanded=False):
                    if ds_desc:
                        st.write(ds_desc)
                    if org_link:
                        st.write(f"**Provider link:** {org_link}")

        st.markdown("---")

        # -------- Distributions --------
        st.subheader("Distributions")

        dists = meta.get("distributions", [])
        if not dists:
            st.caption("No distributions listed.")
        else:
            for dist in dists:
                dist_id = dist.get("id", "Distribution")
                controllers = dist.get("data_controllers", "")

                with st.expander(f"{dist_id}", expanded=False):
                    if controllers:
                        st.write(f"**Data controller(s):** {controllers}")
                    else:
                        st.caption("No data controller information provided.")

        st.caption("Close this dialog to return to the dashboard.")

    _modal()


def dashboard_view():
    
    top_navbar()
    st.markdown("---")

    # Auto refresh every 10 minutes
    AUTO_REFRESH_SECONDS = 600  # 10 minutes
    now = time.time()

    selected_topic_key = st.session_state.get("selected_topic_key", None)

    if st.session_state.get("endpoints_initialized") and selected_topic_key:
        if now - st.session_state["last_auto_refresh"] > AUTO_REFRESH_SECONDS:
            st.session_state["last_auto_refresh"] = now
            st.session_state["status_refresh_key"] += 1

    user = st.session_state.get("user")
    if not user:
        start_transition()
        return
    
    if "selected_platform" not in st.session_state:
        st.session_state.selected_platform = None


    left_col, center_col, right_col = st.columns([3, 5, 4])

    # ---------- LEFT ----------
    with left_col:
        # ---- User Profile card ----
        display_name = user.get("display_name", user.get("username"))
        # Build initials from display name (max 2 letters)
        name_parts = str(display_name).split()
        initials = "".join(part[0].upper() for part in name_parts[:2]) if name_parts else "U"

        st.markdown('<div class="fl-card">', unsafe_allow_html=True)

        header_cols = st.columns([7, 3], vertical_alignment="center")

        with header_cols[0]:
            st.markdown(
                f"""
                <div class="user-profile-header">
                    <div class="user-avatar">{initials}</div>
                    <div class="user-profile-header-title">User Profile</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with header_cols[1]:
            st.markdown('<div class="hdr-btn-right">', unsafe_allow_html=True)
            if st.button("⚙️", key="open_settings", type="secondary", help="Settings"):
                st.session_state["route"] = "settings_account"
                start_transition()

            st.markdown("</div>", unsafe_allow_html=True)

        st.write(f"**User:** {display_name}")
        st.write(f"**Role:** {user.get('role', 'viewer')}")
        st.markdown("</div>", unsafe_allow_html=True)


        # ---- Topic card ----
        st.markdown('<div class="fl-card">', unsafe_allow_html=True)
        st.markdown("#### Topic")

        topic_label_to_key = {
            "Sexual Violence": "sexual_violence",
            "Human Trafficking": "human_trafficking",
            "Refugee Data": "refugee",
            "Health Data": "health",
        }

        topic_labels = ["Choose a topic"] + list(topic_label_to_key.keys())

        topic_label = st.selectbox(
            "Topic",
            topic_labels,
            index=0,  # default to Choose a topic
            label_visibility="collapsed",
        )

        selected_topic_key = topic_label_to_key.get(topic_label)  # None if "Choose a topic"
        st.session_state["selected_topic_key"] = selected_topic_key

        # Detect topic changes and reset auto-init flag
        if selected_topic_key != st.session_state.get("last_topic_key"):
            st.session_state["last_topic_key"] = selected_topic_key
            st.session_state["auto_init_done_for_topic"] = False

        # Auto-initialize endpoints as soon as a real topic is selected
        if selected_topic_key and not st.session_state.get("endpoints_initialized") and not st.session_state.get("auto_init_done_for_topic"):
            st.session_state["status_refresh_key"] += 1
            st.session_state["last_auto_refresh"] = time.time()
            st.session_state["endpoints_initialized"] = True
            st.session_state["auto_init_done_for_topic"] = True
            st.rerun()


        st.markdown("</div>", unsafe_allow_html=True)

        # ---- Platform Endpoints card ----
        st.markdown('<div class="fl-card">', unsafe_allow_html=True)

        # Header row: title (left) + button (right)
        hdr_l, hdr_r = st.columns([7, 3], vertical_alignment="center")
        with hdr_l:
            st.markdown("#### FieldLab SPARQL Endpoints")
        with hdr_r:
            # right-aligned button
            st.markdown('<div class="hdr-btn-right hdr-icon-btn">', unsafe_allow_html=True)
            disable_refresh = (selected_topic_key is None)
            refresh_clicked = st.button("🔄", key="refresh_statuses", type="secondary", help="Refresh endpoints", disabled=disable_refresh)
            st.markdown("</div>", unsafe_allow_html=True)
            
        if selected_topic_key is None:
            st.info("Choose a topic to use dashboard")
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            # load static platform list instantly
            platforms = load_platforms_static()

            # Manual refresh trigger
            if refresh_clicked:
                st.session_state["status_refresh_key"] += 1
                st.session_state["last_auto_refresh"] = time.time()
                st.session_state["endpoints_initialized"] = True
                st.rerun()
            if not st.session_state.get("endpoints_initialized"):
                st.info("Loading endpoints…")

            # Overlay live statuses
            status_map = None
            if st.session_state["status_refresh_key"] > 0:
                placeholder = st.empty()
                with placeholder.container():
                    st.info("Checking endpoint statuses...")
                status_map = load_health_status_map(st.session_state["status_refresh_key"])
                placeholder.empty()

                for name, data in platforms.items():
                    live = status_map.get(name)
                    if live and "status" in live:
                        data["status"] = live["status"]
                    else:
                        data["status"] = data.get("status", "unknown")
            else:
                for name, data in platforms.items():
                    data["status"] = data.get("status", "unknown")

            # Filter platforms by selected topic
            filtered_platforms = {
                key: data
                for key, data in platforms.items()
                if selected_topic_key in data.get("topics", [])
            }

            # Auto-select an online platform if none selected
            if st.session_state.selected_platform is None and filtered_platforms:
                for k, d in filtered_platforms.items():
                    if str(d.get("status", "unknown")).lower() == "online":
                        st.session_state.selected_platform = k
                        break

            # Render platform buttons
            if filtered_platforms:
                for key, data in filtered_platforms.items():
                    raw_status = data.get("status", "unknown")
                    status = str(raw_status).lower()

                    if status == "online":
                        status_class = "status-online"
                    elif status in ("offline", "error"):
                        status_class = "status-offline"
                    elif status == "degraded":
                        status_class = "status-degraded"
                    else:
                        status_class = "status-unknown"

                    row_dot, row_btn = st.columns([0.06, 0.94], gap="small")

                    with row_dot:
                        st.markdown(f"<span class='status-dot {status_class}'></span>", unsafe_allow_html=True)

                    with row_btn:
                        # Show a friendly name if present (fallback to key)
                        display = data.get("name", key)

                        label = f"{display}"
                        clicked = st.button(label, key=f"platbtn_{key}", width="stretch", type="tertiary")

                        if clicked:
                            st.session_state.selected_platform = key
                            st.session_state["open_fdp_modal"] = True
                            st.rerun()

                # Open FDP modal for selected platform
                if st.session_state.get("open_fdp_modal") and st.session_state.get("selected_platform"):
                    st.session_state["open_fdp_modal"] = False
                    render_fdp_modal(st.session_state["selected_platform"])
            else:
                st.write("No platforms available for this topic.")
                
            st.markdown("</div>", unsafe_allow_html=True)

    # ---------- CENTER ----------
    with center_col:
        st.subheader("Proposed Queries")

        queries = fetch_queries()
        current_topic_key = st.session_state.get("selected_topic_key", None)
        if not current_topic_key:
            st.info("Choose a topic to see routine queries.")
            return
        
        filtered_queries = [q for q in queries if q.get("topic") == current_topic_key]
        query_titles = {q["title"]: q for q in filtered_queries} if filtered_queries else {}

        selected_title = st.selectbox(
            "Select a routine query",
            list(query_titles.keys()) if query_titles else ["No queries available"]
        )

        selected_query = query_titles.get(selected_title)

        if selected_query:
            st.markdown(f"**Description:** {selected_query.get('description', '')}")
            st.markdown(f"**Visualization:** {selected_query.get('visualization', '')}")

            allowed_eps = selected_query.get("allowed_endpoints", [])
            selected_eps = st.multiselect(
                "Choose platforms to query",
                options=allowed_eps,
                default=allowed_eps,
                help="Deselect a platform if you want to exclude its data for this query."
            )


            # SPARQL preview from file (if available)
            query_file = selected_query.get("query_file")
            sparql_txt = ""
            if query_file and Path(query_file).exists():
                try:
                    sparql_txt = Path(query_file).read_text(encoding="utf-8")
                except Exception:
                    sparql_txt = f"-- Unable to load SPARQL from {query_file}"
            else:
                sparql_txt = f"-- SPARQL for: {selected_query.get('id')} (file not found)"

            st.text_area(
                "SPARQL (preview)",
                value=sparql_txt,
                height=200,
                disabled=True
            )

            # Permission gating for "Run Query"
            can_use = (st.session_state.get("user", {}).get("dashboard_access") == "use")

            run_clicked = st.button(
                "Run Query",
                key="run_query_btn",
                type="secondary",
                disabled=not can_use
            )

            if not can_use:
                st.info("Your dashboard permission is set to 'view' mode. Ask an admin to enable 'use' mode to run queries.")

            if run_clicked:
                with st.spinner("Running query..."):
                    try:
                        query_id = selected_query["id"]
                        result = run_query(query_id, selected_eps)

                        # 👉 Only use merge_count_results for the FL mock incidents-by-country query
                        if query_id == "fl_incidents_by_country":
                            df = merge_count_results(result, group_var="country")
                            st.session_state["last_result_df"] = df.copy() ## for right side visualization

                            if df.empty:
                                st.warning("No results returned from any selected endpoint.")
                            else:
                                st.subheader("Merged Results (Mock incidents by country)")
                                st.dataframe(df)

                                chart = (
                                    alt.Chart(df)
                                    .mark_bar()
                                    .encode(
                                        x="country:N",
                                        y="total_count:Q",
                                        tooltip=["country", "total_count"],
                                    )
                                    .properties(
                                        title="Incidents by Country (Merged Across FL mock endpoints)"
                                    )
                                )
                                st.altair_chart(chart, width="stretch")

                        else:
                            # For all other queries, just show the raw rows per endpoint
                            st.subheader("Raw results")

                            if not result:
                                st.warning("No results returned.")
                            else:
                                for endpoint, ep_result in result.items():
                                    st.markdown(f"**Endpoint:** {endpoint}")

                                    if isinstance(ep_result, dict) and "error" in ep_result:
                                        st.error(f"Error from {endpoint}: {ep_result['error']}")
                                        continue

                                    bindings = ep_result.get("results", {}).get("bindings", [])
                                    if not bindings:
                                        st.info(f"{endpoint}: no rows.")
                                        continue

                                    rows = [
                                        {var: cell.get("value") for var, cell in b.items()}
                                        for b in bindings
                                    ]
                                    df = pd.DataFrame(rows)
                                    st.dataframe(df)
                                    st.session_state["last_result_df"] = df.copy() ## for right side visualization

                    except Exception as e:
                        st.error(f"Error running query: {e}")

        else:
            st.info("No query selected or no queries available for the chosen topic.")

    # ---------- RIGHT ----------
    with right_col:

        current_topic_key = st.session_state.get("selected_topic_key", None)
        if not current_topic_key:
            st.info("Choose a topic to see routine queries.")
            return
        
        st.subheader("Visuals for Routine Queries")
        df = st.session_state.get("last_result_df")
        
        if df is None or df.empty:
            st.info("Run a query to see summary visuals.")
            return
        
        # ---------- Gender Pie Chart ----------
        gender_col = None
        for c in df.columns:
            if c.lower() == "gender":
                gender_col = c
                break

        if gender_col:
            gender_df = (
                df[gender_col]
                .apply(normalize_gender)
                .value_counts()
                .reset_index()
            )
            gender_df.columns = ["gender", "count"]

        # Fixed color mapping
            gender_colors = {
                "Female": "#f7b6d2",   # light pink
                "Male": "#aec7e8",     # light blue
                "Unknown": "#c7c7c7"   # neutral grey
                }
            
            chart = (
                alt.Chart(gender_df)
                .mark_arc(innerRadius=40)
                .encode(
                    theta=alt.Theta(field="count", type="quantitative"),
                    color=alt.Color(
                        field="gender",
                        type="nominal",
                        scale=alt.Scale(
                            domain=list(gender_colors.keys()),
                            range=list(gender_colors.values())
                            ),
                        legend=alt.Legend(title="Gender")
                    ),
                    tooltip=["gender", "count"]
                    )
                    .properties(
                        title="Victims by Gender"
                        )
            )

            st.altair_chart(chart, width="stretch")

        #else:
        #    st.caption("Gender information not available for this query.")

        # ---------- Grouped Chart for Victims by Age Group ----------
        st.markdown("### Topic Insights")
        
        if selected_topic_key == "sexual_violence":
            st.markdown("#### Sexual Violence Victims by Age Group")

            can_use = (st.session_state.get("user", {}).get("dashboard_access") == "use")
            if not can_use:
                st.info("You don’t have permission to run queries. Please login with a user that has query access.")
            else:
                # Always visible chart: run its routine query independent of dropdown selection
                # Uses allowed_endpoints from query_config.json automatically.
                try:
                    # Tie cache invalidation to status_refresh_key so a manual refresh can also refresh this chart
                    results = run_fixed_topic_query_cached("victims_by_age_group", st.session_state.get("status_refresh_key", 0))
                except Exception as e:
                    st.error(f"Could not run fixed chart query: {e}")
                    results = {}

                df_age = sparql_grouped_counts_to_df(results, group_var="ageGroup")

                if df_age.empty:
                    st.info("No age-group data returned from the configured platforms.")
                else:
                    chart = (
                        alt.Chart(df_age)
                        .mark_bar()
                        .encode(
                            x=alt.X("ageGroup:N", title="Age group"),
                            xOffset="platform:N",
                            y=alt.Y("count:Q", title="Victims"),
                            color=alt.Color("platform:N", title="Platform"),
                            tooltip=["platform", "ageGroup", "count"]
                        )
                        .properties(height=320)
                    )
                    st.altair_chart(chart, use_container_width=True)
        

def account_view():
    refresh_me()
    user = st.session_state.get("user", {})
    st.markdown("#### Account information")
    st.write(f"**Name:** {user.get('display_name', '-')}")
    st.write(f"**Username:** {user.get('username', '-')}")
    st.write(f"**Role:** {user.get('role', '-')}")
    st.write(f"**Dashboard access:** {user.get('dashboard_access', '-')}")
    st.markdown("---")
    if st.button("Back to dashboard", type="secondary"):
        st.session_state["route"] = "dashboard"
        st.session_state["settings_menu_open"] = False
        start_transition()


def admin_view():
    refresh_me()
    user = st.session_state.get("user", {})
    if user.get("role") not in {"admin", "Super_Admin"}:
        st.error("Admin privileges required.")
        return


    st.markdown("#### Admin controls")
    st.caption("Manage roles and dashboard permissions for users.")

    try:
        r = requests.get(USERS_URL, headers=auth_headers(), timeout=15)
        r.raise_for_status()
        users = r.json()
    except Exception as e:
        st.error(f"Could not load users: {e}")
        return

    if not users:
        st.info("No users found.")
        return

    access_options = ["none", "view", "use"]
    role_options = ["user", "admin"]
    

    # Track changes locally (session)
    if "pending_user_updates" not in st.session_state:
        st.session_state["pending_user_updates"] = {}

    pending = st.session_state["pending_user_updates"]

    # Render editable rows (NO per-row save)
    for u in users:
        username = u["username"]
        col1, col2, col3 = st.columns([3, 2, 2])
        is_super_admin = u.get("role") == "Super_Admin"
        is_self = username == st.session_state["user"]["username"]
        current_role = normalize_role_ui(u.get("role", "user"))

        with col1:
            label = u.get("display_name", username)
            if is_self:
                label += " (you)"
            st.write(f"**{label}**")

            st.caption(username)

        with col2:
            if is_super_admin or is_self:
                st.selectbox("Role", [current_role], index=0, key=f"role_{username}", disabled=True, label_visibility="collapsed")
                new_role = current_role
            else:
                new_role = st.selectbox("Role", role_options, index=role_options.index(current_role), key=f"role_{username}", label_visibility="collapsed")


        with col3:
            if is_super_admin or is_self:
                st.selectbox("Dashboard", ["use"], index=0, key=f"dash_{username}", disabled=True, label_visibility="collapsed")
                new_access = "use"
            else:
                new_access = st.selectbox("Dashboard", access_options, index=access_options.index(u.get("dashboard_access", "none")), key=f"dash_{username}", label_visibility="collapsed")

        # Store only if changed
        if not is_super_admin and not is_self:
            if new_role != u.get("role", "user") or new_access != u.get("dashboard_access", "none"):
                pending[username] = {"role": new_role, "dashboard_access": new_access}
            else:
                pending.pop(username, None)

    st.markdown("---")

    btn_left, btn_right = st.columns([1, 1])

    with btn_left:
        back_clicked = st.button(
            "Back to dashboard",
            key="admin_back",
            type="secondary"
        )

    with btn_right:
        # Right-align Save button
        st.markdown('<div class="hdr-btn-right">', unsafe_allow_html=True)
        save_clicked = st.button(
            "Save changes",
            key="save_all_admin",
            type="secondary",
            disabled=(len(pending) == 0)
        )
        st.markdown('</div>', unsafe_allow_html=True)

    if save_clicked:
        errors = []
        updated = 0
        for username, payload in pending.items():
            try:
                pr = requests.patch(
                    f"{USERS_URL}/{username}",
                    json=payload,
                    headers=auth_headers(),
                    timeout=15
                )
                pr.raise_for_status()
                updated += 1
            except Exception as e:
                errors.append(f"{username}: {e}")

        st.session_state["pending_user_updates"] = {}

        if errors:
            st.error("Some updates failed:\n" + "\n".join(errors))
        else:
            st.success(f"Saved {updated} change(s).")

        refresh_me()
        start_transition()

    if back_clicked:
        st.session_state["route"] = "dashboard"
        st.session_state["settings_menu_open"] = False
        start_transition()


def settings_view():
    refresh_me()
    user = st.session_state.get("user", {})
    role = normalize_role_ui(user.get("role", "user"))

    # Column widths mimic a drawer: narrow when closed, wider when open
    if st.session_state["settings_menu_open"]:
        menu_col, divider_col, content_col = st.columns([2, 0.15, 10])
    else:
        menu_col, content_col = st.columns([1, 11])
        divider_col = None

    with menu_col:
        if st.button("☰", key="hamburger_settings", type="secondary"):
            st.session_state["settings_menu_open"] = not st.session_state["settings_menu_open"]
            start_transition()

        if st.session_state["settings_menu_open"]:
            if st.button("Account", key="menu_account", type="secondary"):
                st.session_state["route"] = "settings_account"
                start_transition()

            if role in {"admin", "Super_Admin"}:
                if st.button("Admin", key="menu_admin", type="secondary"):
                    st.session_state["route"] = "settings_admin"
                    start_transition()

    if divider_col is not None:
        with divider_col:
            st.markdown('<div class="settings-v-divider"></div>', unsafe_allow_html=True)
    
    with content_col:
        hdr = st.columns([10, 2])
        with hdr[0]:
            st.markdown("### Settings")
        with hdr[1]:
            if st.button("Logout", type="primary", key="logout_settings"):
                do_logout()
                start_transition()
        st.markdown("---")

        route = st.session_state.get("route", "settings_account")
        if route == "settings_admin":
            admin_view()
        else:
            account_view()

    if "view" not in st.session_state:
        st.session_state["view"] = "dashboard"

def render_transition_screen(text="Switching view…"):
    st.markdown(
        f"""
        <div style="
            position: fixed;
            inset: 0;
            background: #0b0f14;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.2rem;
            color: #ccc;
            z-index: 999999;
        ">
            ⏳ {text}
        </div>
        """,
        unsafe_allow_html=True,
    )

def main():
    load_css()

    if st.session_state.get("is_transitioning"):
        render_transition_screen()
        st.session_state["is_transitioning"] = False
        st.rerun()


    if not (st.session_state.get("logged_in") or find_token()):
        login_view()
        return

    # Ensure we have latest permissions
    refresh_me()
    
    user = st.session_state.get("user", {})
    route = st.session_state.get("route", "dashboard")



    # If user has no dashboard access, force them into Settings → Account
    # Permission gate
    if user.get("dashboard_access", "none") == "none" and route == "dashboard":
        st.warning("You don’t have dashboard access. Contact an admin to enable it.")
        st.session_state["route"] = "settings_account"
        route = "settings_account"

    # Normalize layout state
    if route == "dashboard":
        st.session_state["settings_menu_open"] = False

    # Render
    if route.startswith("settings_"):
        settings_view()
    else:
        dashboard_view()


if __name__ == "__main__":
    main()