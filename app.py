import time
import json
import requests
import streamlit as st
import pandas as pd
import altair as alt
from pathlib import Path

from mainEngine import merge_count_results
from endpoint_health_check import health_check

# ---------- App config ----------
st.set_page_config(page_title="Federated Lighthouse Dashboard", layout="wide")

# session defaults
if "user_menu_select" not in st.session_state:
    st.session_state["user_menu_select"] = "👤"

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if "token" not in st.session_state:
    st.session_state["token"] = None

if "user" not in st.session_state:
    st.session_state["user"] = None

# ---------- Configuration ----------
API_BASE = "http://127.0.0.1:8000"
LOGIN_URL = f"{API_BASE}/login"
QUERIES_URL = f"{API_BASE}/queries"
RUN_QUERY_URL = f"{API_BASE}/run_query"

ENDPOINTS_CONFIG_PATH = Path("config") / "endpoints_config.json"


# ---------- Auth helpers ----------
def find_token():
    return st.session_state.get("token")


def auth_headers():
    token = find_token()
    if token:
        return {"Authorization": f"Bearer {token}"}
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


@st.cache_data(ttl=60)
def load_organizations():
    """
    Load endpoint metadata from config and overlay dynamic health status.

    - Base data (name, type, topics, description, etc.) comes from
      config/endpoints_config.json.
    - Live status (online/offline/degraded/error) comes from endpoint_health_check.health_check().
    """
    # 1) Load static config
    if ENDPOINTS_CONFIG_PATH.exists():
        with ENDPOINTS_CONFIG_PATH.open("r", encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        try:
            with open("endpoints_config.json", "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

    orgs = cfg.get("organizations", {})

    # 2) Fetch live health info
    try:
        status_map = health_check()   # returns {"DPO": {...}, "FL1_MOCK": {...}, ...}
    except Exception as e:
        # If health check fails for some reason, just return static config
        print(f"Warning: health_check failed: {e}")
        return orgs

    # 3) Overlay status onto each org
    for name, data in orgs.items():
        live = status_map.get(name)
        if live and "status" in live:
            data["status"] = live["status"]
        else:
            # keep existing or default to 'unknown'
            data["status"] = data.get("status", "unknown")

    return orgs


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
        st.markdown(
            """
            <style>
            /* Style ALL Streamlit buttons */
            div.stButton > button {
                background-color: #facc15 !important;   /* yellow */
                color: #111827 !important;               /* very dark gray (almost black) */
                font-weight: 800 !important;             /* extra bold */
                font-size: 1rem !important;              /* bigger text */
                border: 1px solid #eab308 !important;
                padding: 0.45rem 1rem !important;
                border-radius: 0.45rem !important;
                box-shadow: 0 0 10px rgba(234, 179, 8, 0.40);
            }

            div.stButton > button:hover {
                background-color: #fbbf24 !important;
                box-shadow: 0 0 14px rgba(250, 204, 21, 0.75);
                color: #000000 !important;               /* pure black on hover */
            }
            </style>
            """,
            unsafe_allow_html=True
        )

        if st.button("⏻ Logout"):
            do_logout()



def login_view():
    # Page title not at the very top, we’ll use custom layout instead
    st.markdown(
        """
        <style>
        /* Make main background dark-ish (optional) */
        .stApp {
            background-color: #0e1117;
        }
        /* Use more of the vertical space */
        .block-container {
        padding-top: 20vh;
        padding-bottom: 12vh;
    }
        </style>
        """,
        unsafe_allow_html=True,
    )

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
            <div style="
                background-color: #111827;
                padding: 2.0rem 2.0rem 1.5rem 2.0rem;
                border-radius: 0.75rem;
                box-shadow: 0 10px 30px rgba(0,0,0,0.45);
                color: #e5e7eb;
                ">
                <h3 style="margin-top: 0; margin-bottom: 0.5rem;">Federated Lighthouse – Login</h3>
                <p style="font-size: 0.9rem; color:#9ca3af; margin-bottom: 1.5rem;">
                    Please log in to use the dashboard.
                </p>
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
            else:
                st.error(f"Login failed: {err}")


def dashboard_view():
    top_navbar()
    st.markdown("---")

    user = st.session_state.get("user")
    if not user:
        safe_rerun()
        return
    
    # Card + avatar + status-dot styling
    st.markdown(
        """
        <style>
        /* Page background (dashboard only) */
        .stApp {
            background-color: #0e1117;  /* dark charcoal / almost black */
        }

        /* Generic card used in left column */
        .fl-card {
            background-color: #0b1220;          /* slightly lighter than page */
            padding: 1rem 1.25rem;
            border-radius: 1rem;                /* squircle corners */
            border: 1px solid #1f2937;          /* subtle border */
            margin-bottom: 1.1rem;              /* space between cards */
            box-shadow: 0 10px 22px rgba(0,0,0,0.65);  /* deeper shadow */
        }
        .fl-card h4, .fl-card h3, .fl-card h2, .fl-card h1, .fl-card h5 {
            margin-top: 0;
            margin-bottom: 0.75rem;
        }

        /* Shiny status dots */
        .status-dot {
            display: inline-block;
            width: 0.7rem;
            height: 0.7rem;
            border-radius: 9999px;
            margin-right: 0.4rem;
        }

        /* Online: brighter + pulsing */
        .status-online {
            background: #22c55e;
            box-shadow: 0 0 12px rgba(34, 197, 94, 1);
            animation: pulse-green 1.4s ease-in-out infinite;
        }

        /* Other states: brighter shine but no animation */
        .status-unknown {
            background: #f97373;
            box-shadow: 0 0 10px rgba(248, 113, 113, 0.95);
        }
        .status-offline, .status-error {
            background: #dc2626;
            box-shadow: 0 0 10px rgba(220, 38, 38, 0.95);
        }
        .status-degraded {
            background: #eab308;
            box-shadow: 0 0 10px rgba(234, 179, 8, 0.95);
        }

        /* Pulsing animation for online endpoints */
        @keyframes pulse-green {
            0% {
                transform: scale(1);
                box-shadow: 0 0 8px rgba(34, 197, 94, 0.8);
            }
            50% {
                transform: scale(1.25);
                box-shadow: 0 0 18px rgba(34, 197, 94, 1);
            }
            100% {
                transform: scale(1);
                box-shadow: 0 0 8px rgba(34, 197, 94, 0.8);
            }
        }

        /* User avatar + header */
        .user-profile-header {
            display: flex;
            align-items: center;
            gap: 0.6rem;
            margin-bottom: 0.5rem;
        }
        .user-avatar {
            width: 2.1rem;
            height: 2.1rem;
            border-radius: 9999px;
            background: linear-gradient(135deg, #1f2937, #4b5563);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            font-size: 0.95rem;
            color: #e5e7eb;
            box-shadow: 0 0 10px rgba(0,0,0,0.7);
        }
        .user-profile-header-title {
            font-weight: 600;
            font-size: 1.05rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


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
            "",
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
        st.markdown("#### Organization Endpoints")

        orgs = load_organizations()

        # Filter orgs by selected topic
        filtered_orgs = {
            key: data
            for key, data in orgs.items()
            if selected_topic_key in data.get("topics", [])
        }

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

                st.markdown(
                    f"<span class='status-dot {status_class}'></span>"
                    f" <strong>{key}</strong> ({data.get('type', 'unknown')}) – status: {raw_status}",
                    unsafe_allow_html=True,
                )
        else:
            st.write("No organizations available for this topic.")


        st.markdown("</div>", unsafe_allow_html=True)

        # ---- FAIR Data Point card ----
        st.markdown('<div class="fl-card">', unsafe_allow_html=True)
        st.markdown("#### FAIR Data Point (metadata)")
        st.write("• Catalogues")
        st.write("• Datasets (based on routine SPARQL queries)")
        st.write("• Data distributions")
        st.write("• Data dashboards")
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

            if st.button("Run Query"):
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
    # full login gate
    if st.session_state.get("logged_in") and find_token():
        dashboard_view()
    else:
        login_view()


if __name__ == "__main__":
    main()
