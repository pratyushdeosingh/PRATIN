import os
os.environ["PRATIN_INTEGRATION_MODE"] = "fixture"
os.environ["PRATIN_DB_PATH"] = "data/test-pratin.db"

from fastapi.testclient import TestClient
from backend.app.main import app, store

client = TestClient(app)


def setup_function():
    store.reset()


def test_valid_invoice_produces_persistent_risk_ledger_entry():
    scenario = client.get("/api/scenarios").json()["urgent"]
    created = client.post("/api/opportunities", json=scenario).json()
    opp_id = created["id"]

    # Before market run, no risk ledger entry exists
    assert client.get(f"/api/risk-ledger/{opp_id}").status_code == 404
    assert len(client.get("/api/risk-ledger").json()) == 0

    # Run market
    cleared = client.post(f"/api/opportunities/{opp_id}/run-market").json()
    assert cleared["status"] == "MARKET_RUN"

    # Ledger entry is now retrievable
    ledger = client.get("/api/risk-ledger").json()
    assert len(ledger) == 1
    entry = ledger[0]

    assert entry["opportunity_id"] == opp_id
    assert entry["invoice_number"] == scenario["invoice"]["invoice_number"]
    assert entry["supplier_name"] == scenario["invoice"]["supplier_name"]
    assert entry["buyer_name"] == scenario["invoice"]["buyer_name"]
    assert entry["amount"] == scenario["invoice"]["amount"]
    assert entry["evaluated_at"] is not None

    # Verification result check
    assert entry["verification"]["status"] == "VERIFIED"
    assert entry["verification"]["confidence"] >= 0.7
    assert len(entry["verification"]["verified_fields"]) > 0
    assert "Synthetic rule-based verification" in entry["verification"]["simulation_notice"]

    # Risk score, band, confidence check
    assert isinstance(entry["risk"]["score"], (int, float))
    assert entry["risk"]["band"] in ["LOW", "MODERATE", "HIGH", "SEVERE"]
    assert 0 <= entry["risk"]["confidence"] <= 1.0

    # Factor-level explainability check
    assert len(entry["risk"]["factors"]) >= 3
    assert len(entry["verification"]["reason_codes"]) > 0
    for factor in entry["risk"]["factors"]:
        assert factor["label"]
        assert factor["impact"] in ["positive", "negative", "neutral"]
        assert factor["explanation"]
        assert isinstance(factor["points"], (int, float))
        assert factor["reason_code"] is not None

    # Single entry endpoint by opportunity_id and by entry id
    by_opp = client.get(f"/api/risk-ledger/{opp_id}")
    assert by_opp.status_code == 200
    assert by_opp.json()["id"] == entry["id"]

    by_id = client.get(f"/api/risk-ledger/{entry['id']}")
    assert by_id.status_code == 200
    assert by_id.json()["opportunity_id"] == opp_id


def test_multiple_invoices_produce_separate_ledger_entries():
    scenarios = client.get("/api/scenarios").json()
    urgent = scenarios["urgent"]
    strong = scenarios["strong"]

    # Create and clear first opportunity
    opp1 = client.post("/api/opportunities", json=urgent).json()
    client.post(f"/api/opportunities/{opp1['id']}/run-market")

    # Create and clear second opportunity
    opp2 = client.post("/api/opportunities", json=strong).json()
    client.post(f"/api/opportunities/{opp2['id']}/run-market")

    # Verify ledger contains 2 distinct entries
    ledger = client.get("/api/risk-ledger").json()
    assert len(ledger) == 2
    opp_ids = {entry["opportunity_id"] for entry in ledger}
    assert opp_ids == {opp1["id"], opp2["id"]}

    inv_numbers = {entry["invoice_number"] for entry in ledger}
    assert inv_numbers == {urgent["invoice"]["invoice_number"], strong["invoice"]["invoice_number"]}


def test_audit_event_logged_on_risk_evaluation():
    scenario = client.get("/api/scenarios").json()["urgent"]
    created = client.post("/api/opportunities", json=scenario).json()
    client.post(f"/api/opportunities/{created['id']}/run-market")

    audits = client.get("/api/audit").json()
    event_types = [a["event_type"] for a in audits]
    assert "RISK_EVALUATED" in event_types
