import pandas as pd
import altair as alt
import streamlit as st
import requests
from mainEngine import merge_count_results

API_BASE = "http://127.0.0.1:8000"


@st.cache_data
def fetch_queries():
    resp = requests.get(f"{API_BASE}/queries")
    resp.raise_for_status()
    return resp.json()


def run_query(query_id: str, endpoints: list[str] | None = None):
    payload = {"query_id": query_id}
    if endpoints:
        payload["endpoints"] = endpoints
    resp = requests.post(f"{API_BASE}/run_query", json=payload)
    resp.raise_for_status()
    return resp.json()


def main():
    st.set_page_config(page_title="Federated Lighthouse Dashboard", layout="wide")

    st.title("Federated Lighthouse Dashboard – Prototype")

    # Layout: 3 columns (left, center, right)
    col_left, col_center, col_right = st.columns([1, 2, 1])

    # ---------- LEFT COLUMN ----------
    with col_left:
        st.subheader("User / Access")
        st.write("User: Donald Trump")  # placeholder
        st.write("Access: 2 data sources")  # placeholder

        st.subheader("Topic")
        topic = st.selectbox(
            "Select topic",
            ["sexual_violence"],  # extend later with other topics
            index=0
        )

        st.subheader("Organization Endpoints")
        st.write("- SORD (local Fuseki) [status TBD]")

        st.subheader("FAIR Data Point (metadata)")
        st.write("• Catalogues")
        st.write("• Datasets (based on routine SPARQL queries)")
        st.write("• Data distributions")
        st.write("• Data dashboards")

    # ---------- CENTER COLUMN ----------
    with col_center:
        st.subheader("Proposed Queries")

        queries = fetch_queries()
        # Filter by topic (for now only sexual_violence exists)
        filtered_queries = [q for q in queries if q["topic"] == topic]

        query_titles = {q["title"]: q for q in filtered_queries}

        selected_title = st.selectbox(
            "Select a routine query",
            list(query_titles.keys()) if query_titles else ["No queries available"]
        )

        selected_query = query_titles.get(selected_title)

        if selected_query:
            st.markdown(f"**Description:** {selected_query['description']}")
            st.markdown(f"**Visualization:** {selected_query['visualization']}")

            # Let the user choose which organizations to include
            allowed_eps = selected_query.get("allowed_endpoints", [])
            selected_eps = st.multiselect(
                "Choose organizations to query",
                options=allowed_eps,
                default=allowed_eps,
                help="Deselect an organization if you want to exclude its data for this query."
            )

            # Show read-only SPARQL (optional: you can load file contents later)
            st.text_area(
                "SPARQL (preview)",
                value=f"-- SPARQL for: {selected_query['id']}\n-- Will show actual query text later.",
                height=200,
                disabled=True
            )

            if st.button("Run Query"):
                with st.spinner("Running query..."):
                    try:
                        result = run_query(selected_query["id"], selected_eps)
                        st.success("Query executed.")

                        # Merge per-endpoint results
                        df = merge_count_results(result, group_var="country")

                        if df.empty:
                            st.warning("No results returned from any selected endpoint.")
                        else:
                            st.subheader("Merged Results")
                            st.dataframe(df)

                            # Plot bar chart
                            chart = (
                                alt.Chart(df)
                                .mark_bar()
                                .encode(
                                    x="country:N",
                                    y="total_count:Q",
                                    tooltip=["country", "total_count"]
                                )
                                .properties(
                                    title="Incidents by Country (Merged Across Endpoints)"
                                )
                            )
                            st.altair_chart(chart, use_container_width=True)

                    except Exception as e:
                        st.error(f"Error running query: {e}")

    # ---------- RIGHT COLUMN ----------
    with col_right:
        st.subheader("Visuals for Routine Queries")
        st.write("Visualizations will appear here once we shape the result data.")


if __name__ == "__main__":
    main()
