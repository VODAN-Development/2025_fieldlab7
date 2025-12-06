import requests

url = "http://127.0.0.1:8000/run_query"
payload = {"query_id": "incidents_by_type"}

response = requests.post(url, json=payload)

print("Status code:", response.status_code)
print("Response:", response.json())
