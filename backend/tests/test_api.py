import os
os.environ["PRATIN_INTEGRATION_MODE"]="fixture"
os.environ["PRATIN_DB_PATH"]="data/test-pratin.db"
from fastapi.testclient import TestClient
from backend.app.main import app, store

client=TestClient(app)

def setup_function(): store.reset()

def test_full_invoice_to_settlement_loop_changes_liquidity_and_audit():
    scenario=client.get("/api/scenarios").json()["urgent"]
    created=client.post("/api/opportunities",json=scenario).json()
    cleared=client.post(f"/api/opportunities/{created['id']}/run-market").json()
    assert cleared["evaluation"]["verification"]["status"] == "VERIFIED"
    recommendation=cleared["match"]["recommended_offer_id"]
    assert recommendation
    winning=next(x for x in cleared["match"]["ranked_offers"] if x["offer"]["id"]==recommendation)
    before=next(p for p in client.get("/api/providers").json() if p["id"]==winning["offer"]["provider_id"])
    settlement=client.post(f"/api/opportunities/{created['id']}/accept/{recommendation}")
    assert settlement.status_code == 200 and settlement.json()["status"] == "SIMULATED_SETTLED"
    after=next(p for p in client.get("/api/providers").json() if p["id"]==winning["offer"]["provider_id"])
    assert after["available_liquidity"] == before["available_liquidity"]-winning["offer"]["financed_amount"]
    assert client.post(f"/api/opportunities/{created['id']}/accept/{recommendation}").status_code == 409
    assert {x["event_type"] for x in client.get("/api/audit").json()} >= {"OPPORTUNITY_CREATED","MARKET_CLEARED","SETTLEMENT_COMPLETED"}
    second_scenario=client.get("/api/scenarios").json()["strong"]
    second=client.post("/api/opportunities",json=second_scenario).json()
    second=client.post(f"/api/opportunities/{second['id']}/run-market").json()
    second_winner=next(x["offer"] for x in second["match"]["ranked_offers"] if x["offer"]["id"]==second["match"]["recommended_offer_id"])
    assert winning["offer"]["provider_id"] == "nbfc-b"
    assert second_winner["provider_id"] == "fund-d"

def test_platform_metrics_are_data_derived():
    metrics=client.get("/api/platform/metrics")
    assert metrics.status_code==200 and metrics.json()["available_liquidity"]>0
