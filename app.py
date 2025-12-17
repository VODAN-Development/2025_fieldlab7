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

# ---------- Configuration ----------
API_BASE = "http://127.0.0.1:8000"
BASE_DIR = Path(__file__).resolve().parent
LOGIN_URL = f"{API_BASE}/login"
QUERIES_URL = f"{API_BASE}/queries"
RUN_QUERY_URL = f"{API_BASE}/run_query"

STYLES_PATH = BASE_DIR / "assets" / "styles.css"
#STYLES_PATH = Path("assets") / "styles.css"
ENDPOINTS_CONFIG_PATH = Path("config") / "endpoints_config.json"
FDP_CONFIG_PATH = Path("config") / "fdp_config.json"


def load_css():
    if STYLES_PATH.exists():
        st.markdown(f"<style>{STYLES_PATH.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
    else:
        st.error(f"styles.css not found at: {STYLES_PATH}")


# ---------- App config ----------
st.set_page_config(page_title="Federated Lighthouse Dashboard", layout="wide")
#load_css()

# ---------- Auth helpers ----------
def find_token():
    return st.session_state.get("token")


def auth_headers():
    token = find_token()
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}

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
            "role": data.get("role", "viewer"),
            "display_name": data.get("display_name", data.get("username"))
        }
        st.session_state["logged_in"] = True
        st.session_state["just_logged_in"] = True
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
        if key in st.session_state:
            del st.session_state[key]
    safe_rerun()


# ---------- Data helpers ----------
@st.cache_data
def fetch_queries_cached(token_present: bool):
    try:
        headers = auth_headers()
        resp = requests.get(QUERIES_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


def fetch_queries():
    token_present = bool(find_token())
    return fetch_queries_cached(token_present)


def run_query(query_id: str, endpoints: list | None = None):
    payload = {"query_id": query_id}
    if endpoints:
        payload["endpoints"] = endpoints
    headers = auth_headers()
    resp = requests.post(RUN_QUERY_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=300)
def load_organizations_static():
    """Load only static endpoint metadata from config (fast, no network)."""
    if ENDPOINTS_CONFIG_PATH.exists():
        with ENDPOINTS_CONFIG_PATH.open("r", encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        cfg = {}
    return cfg.get("organizations", {})

@st.cache_data(ttl=60)
def load_health_status_map(_refresh_key: int):
    """Run live health checks (slow, network). Cache for 60s."""
    return health_check()


def safe_rerun():
    time.sleep(0.1)
    st.rerun()

# ---------- UI components ----------
def top_navbar():
    user = st.session_state.get("user")
    
    # Create a 3-column layout: title | spacer | logout button
    col_title, col_spacer, col_logout = st.columns([10, 1, 1])

    with col_title:
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
                st.success("Login successful.")
                safe_rerun()
                st.stop() 
            else:
                st.error(f"Login failed: {err}")


def dashboard_view():
    # ---- Post-login transition rerun (prevents old login UI lingering during slow loads)
    if st.session_state.get("just_logged_in", False):
        st.session_state["just_logged_in"] = False
        top_navbar()
        st.info("Preparing dashboard…")
        safe_rerun()
        st.stop()
    
    top_navbar()
    st.markdown("---")

    user = st.session_state.get("user")
    if not user:
        safe_rerun()
        return
    
    if "selected_org" not in st.session_state:
        st.session_state.selected_org = None


    left_col, center_col, right_col = st.columns([3, 5, 4])

    # ---------- LEFT ----------
    with left_col:
        # ---- User Profile card ----
        display_name = user.get("display_name", user.get("username"))
        # Build initials from display name (max 2 letters)
        name_parts = str(display_name).split()
        initials = "".join(part[0].upper() for part in name_parts[:2]) if name_parts else "U"

        st.markdown('<div class="fl-card">', unsafe_allow_html=True)
        st.markdown(
            f"""
            <div class="user-profile-header">
                <div class="user-avatar">{initials}</div>
                <div class="user-profile-header-title">User Profile</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
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
        topic_labels = list(topic_label_to_key.keys())

        topic_label = st.selectbox(
            "Topic",
            topic_labels,
            index=0,
            label_visibility="collapsed",
        )
        selected_topic_key = topic_label_to_key[topic_label]
        # store for use in center column
        st.session_state["selected_topic_key"] = selected_topic_key

        st.markdown("</div>", unsafe_allow_html=True)

        # ---- Organization Endpoints card ----
        st.markdown('<div class="fl-card">', unsafe_allow_html=True)

        # Header row: title (left) + button (right)
        hdr_l, hdr_r = st.columns([6, 2], vertical_alignment="center")
        with hdr_l:
            st.markdown("#### Organization Endpoints")
        with hdr_r:
            # right-aligned button
            st.markdown('<div class="hdr-btn-right">', unsafe_allow_html=True)
            refresh_clicked = st.button("Refresh statuses", key="refresh_statuses", type="secondary")
            st.markdown("</div>", unsafe_allow_html=True)

        # 1) Always load static org list instantly
        orgs = load_organizations_static()

        # trigger refresh action
        if refresh_clicked:
            st.session_state["status_refresh_key"] += 1
            safe_rerun()

        # 3) Apply live statuses only if refresh has been triggered at least once
        status_map = None
        if st.session_state["status_refresh_key"] > 0:
            placeholder = st.empty()
            with placeholder.container():
                st.info("Checking endpoint statuses...")
            status_map = load_health_status_map(st.session_state["status_refresh_key"])
            placeholder.empty()

            # overlay statuses onto orgs
            for name, data in orgs.items():
                live = status_map.get(name)
                if live and "status" in live:
                    data["status"] = live["status"]
                else:
                    data["status"] = data.get("status", "unknown")
        else:
            # No live check yet → show unknown (fast first render)
            for name, data in orgs.items():
                data["status"] = data.get("status", "unknown")

        # Filter orgs by selected topic
        filtered_orgs = {
            key: data
            for key, data in orgs.items()
            if selected_topic_key in data.get("topics", [])
        }

        if st.session_state.selected_org is None and filtered_orgs:
            for k, d in filtered_orgs.items():
                if str(d.get("status", "unknown")).lower() == "online":
                    st.session_state.selected_org = k
                    break

        if filtered_orgs:
            for key, data in filtered_orgs.items():
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

                # clickable organization row
                row_dot, row_btn = st.columns([0.06, 0.94], gap="small")

                with row_dot:
                    st.markdown(f"<span class='status-dot {status_class}'></span>", unsafe_allow_html=True)

                with row_btn:
                    is_selected = (st.session_state.selected_org == key)
                    label = f"✅ {key} ({data.get('type', 'unknown')}) – status: {raw_status}" if is_selected else \
                            f"{key} ({data.get('type', 'unknown')}) – status: {raw_status}"

                    clicked = st.button(label, key=f"orgbtn_{key}", use_container_width=True, type="tertiary")

                    if clicked:
                        st.session_state.selected_org = key
                        safe_rerun()


        else:
            st.write("No organizations available for this topic.")


        st.markdown("</div>", unsafe_allow_html=True)

        # ---- FAIR Data Point card ----
        st.markdown('<div class="fl-card">', unsafe_allow_html=True)
        
        fdp_configs = load_fdp_configs()
        selected_org = st.session_state.get("selected_org")

        # Header row: title (left) + clear button (right)
        hdr_l, hdr_r = st.columns([6, 2], vertical_alignment="center")
        with hdr_l:
            st.markdown("#### FAIR Data Point (metadata)")
        with hdr_r:
            st.markdown('<div class="hdr-btn-right">', unsafe_allow_html=True)
            clear_clicked = st.button(
                "Clear selection",
                key="clear_org_selection",
                type="secondary",
                disabled=(not bool(selected_org)),
            )
            st.markdown("</div>", unsafe_allow_html=True)

        if clear_clicked:
            st.session_state.selected_org = None
            safe_rerun()

        if not selected_org:
            st.info("Click an organization above to view its metadata.")
        else:
            org_meta = fdp_configs.get(selected_org)

            if not org_meta:
                st.warning(f"No FDP metadata found for '{selected_org}' in fdp_configs.json.")
            else:
                st.success(f"Showing metadata for: {selected_org}")

                # Catalogues
                cats = org_meta.get("catalogues", [])
                st.markdown("**Catalogues**")
                if not cats:
                    st.caption("No catalogues.")
                else:
                    for c in cats:
                        st.markdown(f"- **{c.get('title','(untitled)')}** — {c.get('description','')}".strip())

                # Datasets
                dsets = org_meta.get("datasets", [])
                st.markdown("**Datasets**")
                if not dsets:
                    st.caption("No datasets.")
                else:
                    for d in dsets:
                        st.markdown(f"- **{d.get('title','(untitled)')}**")
                        if d.get("description"):
                            st.caption(d["description"])
                        if d.get("routine_queries"):
                            st.markdown("  • Queries: " + ", ".join(f"`{q}`" for q in d["routine_queries"]))

                # Distributions
                dists = org_meta.get("distributions", [])
                st.markdown("**Distributions**")
                if not dists:
                    st.caption("No distributions.")
                else:
                    for dist in dists:
                        st.markdown(
                            f"- {dist.get('format','')} | {dist.get('auth','')}  \n"
                            f"  Access URL: `{dist.get('access_url','')}`"
                        )

                # Dashboards
                boards = org_meta.get("dashboards", [])
                st.markdown("**Dashboards**")
                if not boards:
                    st.caption("No dashboards.")
                else:
                    for b in boards:
                        st.markdown(f"- {b.get('title','(untitled)')} (query: `{b.get('query_id','')}`)")

        st.markdown("</div>", unsafe_allow_html=True)

    # ---------- CENTER ----------
    with center_col:
        st.subheader("Proposed Queries")

        queries = fetch_queries()
        current_topic_key = st.session_state.get("selected_topic_key", "sexual_violence")
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
                "Choose organizations to query",
                options=allowed_eps,
                default=allowed_eps,
                help="Deselect an organization if you want to exclude its data for this query."
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

            run_clicked = st.button("Run Query", key="run_query_btn", type="secondary")


            if run_clicked:
                with st.spinner("Running query..."):
                    try:
                        query_id = selected_query["id"]
                        result = run_query(query_id, selected_eps)

                        # 👉 Only use merge_count_results for the FL mock incidents-by-country query
                        if query_id == "fl_incidents_by_country":
                            df = merge_count_results(result, group_var="country")

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
                                st.altair_chart(chart, use_container_width=True)

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

                    except Exception as e:
                        st.error(f"Error running query: {e}")

        else:
            st.info("No query selected or no queries available for the chosen topic.")

    # ---------- RIGHT ----------
    with right_col:
        st.subheader("Visuals for Routine Queries")
        st.write("Visualizations will appear here once we shape the result data.")

    st.markdown("---")
    st.caption("Demo dashboard. Use top-right menu to logout.")


def main():
    load_css()

    # full login gate
    if st.session_state.get("logged_in") or find_token():
        dashboard_view()
    else:
        login_view()


if __name__ == "__main__":
    main()
