FieldLab 7 – Federated Dashboard (Prototype)

This project implements a prototype dashboard for executing routine SPARQL queries across distributed RDF data sources.
The system consists of:

- A SPARQL engine (mainEngine.py) for loading queries and sending them to external SPARQL endpoints
- A FastAPI backend (api.py) that exposes /queries and /run_query
- A Streamlit UI (app.py) that allows users to select topics, choose routine queries, and view results

This prototype is currently running locally and integrates with mock or local SPARQL endpoints.
External FieldLab groups will provide real endpoint URLs and datasets later in the project.


🔧 Setup (Local Development):
1. Create and activate virtual environment:
"python -m venv venv
venv\Scripts\activate   # Windows"

2. Install dependencies
"pip install -r requirements.txt"


▶️ Run Streamlit Dashboard:
"streamlit run app.py"


📁 Project Structure (simplified):
api.py                 # Backend API
mainEngine.py          # SPARQL execution engine
app.py                 # Streamlit dashboard UI
config/
  endpoints_config.json
  query_config.json
queries/
  sexual_violence/
    *.sparql


📌 Status:
- Core engine, API, and UI prototype are functional locally
- Integration with external FieldLab datasets will be added as endpoints become available
- Authentication, metadata display, and visualizations will be implemented in next development phases