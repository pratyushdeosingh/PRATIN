import copy

from backend.tests.test_api import client, store


def _cleared():
    scenario=client.get("/api/scenarios").json()["urgent"]
    created=client.post("/api/opportunities",json=scenario).json()
    response=client.post(f"/api/opportunities/{created['id']}/run-market")
    assert response.status_code == 200
    return response.json()


def setup_function(): store.reset()


def test_digital_twin_is_deterministic_and_never_mutates_state():
    opportunity=_cleared(); before=copy.deepcopy({"providers":client.get("/api/providers").json(),
        "opportunities":client.get("/api/opportunities").json(),"audit":client.get("/api/audit").json(),
        "settlements":client.get("/api/settlements").json()})
    payload={"opportunity_id":opportunity["id"],"overrides":{"max_settlement_hours":12,"market_regime":"STRESSED"}}
    first=client.post("/api/simulations/market-twin",json=payload)
    second=client.post("/api/simulations/market-twin",json=payload)
    assert first.status_code == 200 and first.json() == second.json()
    assert first.json()["notice"].startswith("Pure deterministic")
    after={"providers":client.get("/api/providers").json(),"opportunities":client.get("/api/opportunities").json(),
        "audit":client.get("/api/audit").json(),"settlements":client.get("/api/settlements").json()}
    assert before == after


def test_counterfactual_uses_exact_provider_constraints():
    opportunity=_cleared()
    result=client.get(f"/api/opportunities/{opportunity['id']}/counterfactual/bank-a")
    assert result.status_code == 200
    fields={x["field"] for x in result.json()["hard_constraint_changes"]}
    assert {"max_ticket_size","settlement_hours"} <= fields
    assert "approximate" in result.json()["explanation"]


def test_strategy_stress_and_intelligence_are_explainable_and_non_mutating():
    opportunity=_cleared(); providers=client.get("/api/providers").json()
    strategy=client.post("/api/simulations/strategy",json={"opportunity_id":opportunity["id"],"max_settlement_hours":24})
    assert strategy.status_code == 200 and len(strategy.json()["trade_off_curve"]) == 4
    stress=client.post(f"/api/simulations/stress/{opportunity['id']}")
    assert stress.status_code == 200 and len(stress.json()["scenarios"]) == 6
    assert 0 <= stress.json()["resilience_score"] <= 100 and "Explainable demo" in stress.json()["notice"]
    intel=client.get("/api/market/intelligence")
    assert intel.status_code == 200 and intel.json()["market_health"] in {"HEALTHY","TIGHT","FRAGILE"}
    assert client.get("/api/providers").json() == providers


def test_confidence_stress_is_explicit_and_failed_simulation_is_safe():
    opportunity=_cleared(); before=client.get("/api/opportunities").json()
    stressed=client.post("/api/simulations/market-twin",json={"opportunity_id":opportunity["id"],"overrides":{"confidence_stress":True}})
    assert stressed.status_code == 200
    assert stressed.json()["risk"]["adjusted"] >= stressed.json()["risk"]["raw"]
    failed=client.post("/api/simulations/market-twin",json={"opportunity_id":opportunity["id"],"overrides":{"minimum_amount":99999999}})
    assert failed.status_code == 422 and client.get("/api/opportunities").json() == before
