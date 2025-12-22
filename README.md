# FieldLab 7 – Federated SPARQL Dashboard (Prototype)

This repository contains a **prototype federated dashboard** developed for **FieldLab 7**.
The system enables execution of **predefined (routine) SPARQL queries** across **distributed RDF/SPARQL endpoints** and presents results through a simple web-based interface.

The project is designed as a **local prototype**, with support for mock endpoints and configuration-driven integration of real external datasets provided by FieldLab partners.

---

## 🧩 System Overview

The system consists of three main components:

- **SPARQL Execution Engine**  
  Handles loading of query definitions and execution against configured SPARQL endpoints.

- **Backend API (FastAPI)**  
  Exposes endpoints for listing available queries and executing selected queries.

- **Frontend Dashboard (Streamlit)**  
  Provides a user interface to select data topics, automatically load relevant platforms, visualize topic-specific insights, and optionally execute predefined routine SPARQL queries.

---

## 🛠️ Technologies Used

- Python 3
- FastAPI
- Streamlit
- SPARQLWrapper / RDF tooling
- JSON-based configuration
- Virtual environments for dependency isolation

---

## Important Notes

1. **Python Dependencies**  
   The `requirements.txt` file contains the complete list of Python libraries required to run the application. All dependencies should be installed using `pip install -r requirements.txt` before starting the API or dashboard.

2. **Endpoint Credentials & Sensitive Configuration**  
   - Endpoint Credentials, access tokens, or other sensitive endpoint-related values are currently managed via **local environment variables** and are not stored directly in the repository.
   - User authentication secrets (passwords, JWT secret) are also managed via **local environment variables** and are not stored directly in the repository.  
   - These values are intentionally excluded from version control to avoid exposing sensitive information.

3. **Federated Endpoint Availability**  
   Query results depend on the availability and responsiveness of the configured SPARQL endpoints. Temporary endpoint downtime or network issues may affect query execution and returned results.

4. **FAIR Data Point (FDP) Metadata Integration**
   The dashboard integrates FAIR Data Point–aligned metadata through a local configuration (`fdp_config.json`). This metadata describes applications, datasets, catalogues, distributions and data providers associated with each SPARQL platform. FDP metadata is presented in the UI to provide context, provenance, and governance information alongside query results, without directly querying FDP APIs.

5. **Endpoint Health Monitoring**
   The system performs lightweight health checks on configured SPARQL endpoints to determine availability before query execution. Endpoint status is reflected in the UI and helps prevent execution against offline platforms.

6. **User Authentication and Roles**
   Access to the dashboard is restricted to authenticated users. User roles (e.g., admin, user) control access to administrative functionality such as user and permission management. Authentication details are defined in configuration and secured through environment variables.

7. **Development Status**  
   This project is a prototype developed in the context of FieldLab 7. Some features, configurations, or integrations may be incomplete or subject to change as the project evolves.

---

## 🔧 Setup (Local Development):
1. Create and activate virtual environment:
"python -m venv venv
venv\Scripts\activate   # Windows"

2. Install dependencies:
"pip install -r requirements.txt"

3. ▶️ Run the Backend API (FastAPI):
"uvicorn api:app --reload"

4. ▶️ Run Streamlit Dashboard:
"streamlit run app.py" 

---

## 📁 Project Structured

```text
DSIP_FIELDLAB7_DEV/
│
├── api.py                     # FastAPI backend
├── app.py                     # Streamlit dashboard UI
├── mainEngine.py              # SPARQL execution engine
├── endpoint_health_check.py   # Endpoint availability checks
│
├── assets/                    # UI assets (logos, styles)
│   ├── federated_lighthouse_logo.png
│   ├── federated_lighthouse_logo_dark.png
│   └── styles.css
│
├── config/                    # Configuration files
│   ├── endpoints_config.json  # SPARQL endpoint definitions
│   ├── fdp_config.json        # FDP-related configuration
│   ├── query_config.json     # Query metadata and mappings
│   └── user_config.json      # User-level configuration
│
├── queries/                   # SPARQL query collections
│   ├── constant_queries/
│   ├── fl_mock/
│   ├── human_trafficking/
│   ├── refugee/
│   └── sexual_violence/
│
├── requirements.txt           # Python dependencies
├── README.md                  # Project documentation
├── LICENSE
└── CONTRIBUTING.md

