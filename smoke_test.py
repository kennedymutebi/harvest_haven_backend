import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'harvest_haven.settings')
django.setup()

from django.test import Client

client = Client()

# --- Login to get auth token ---
resp = client.post(
    "/api/auth/login/",
    {"email": "kennedymutebi7@gmail.com", "password": "P@ss12345"},
    content_type="application/json"
)
print("LOGIN:", resp.status_code, resp.json())

token = resp.json()["tokens"]["access"]
auth_header = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

# --- Collector flow ---
resp = client.post("/api/auth/collectors/", {"name": "Peter Kato", "phone_number": "+256701222333"}, content_type="application/json", **auth_header)
print("CREATE COLLECTOR:", resp.status_code, resp.json())
collector_id = resp.json()["id"]

resp = client.post("/api/members/", {"first_name": "Mark", "last_name": "Otim", "collector": collector_id}, content_type="application/json", **auth_header)
print("CREATE MEMBER WITH COLLECTOR:", resp.status_code, resp.json())

resp = client.get("/api/members/", **auth_header)
print("MEMBER LIST (should show collector_name):", resp.status_code, resp.json())

resp = client.post("/api/savings/savings/", {"member": resp.json()["results"][-1]["id"], "amount": "5000", "date": "2026-08-06"}, content_type="application/json", **auth_header)
print("DEPOSIT FOR NEW MEMBER:", resp.status_code, resp.json())

resp = client.get(f"/api/savings/collectors/{collector_id}/summary/?date=2026-08-06", **auth_header)
print("COLLECTOR DAILY SUMMARY:", resp.status_code, resp.json())

resp = client.get(f"/api/savings/collectors/{collector_id}/summary/?month=2026-08", **auth_header)
print("COLLECTOR MONTHLY SUMMARY:", resp.status_code, resp.json())