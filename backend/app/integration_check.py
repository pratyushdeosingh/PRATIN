"""Run the canonical two-allocation story against a live required-mode core."""
import asyncio
import os
import httpx

async def checked(client: httpx.AsyncClient, method: str, path: str, **kwargs):
    response = await client.request(method, path, **kwargs)
    response.raise_for_status()
    return response.json()

async def main():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",timeout=10) as client:
        health = await checked(client, "GET", "/health")
        assert health["mode"] == "required", health
        expected_database = os.getenv("PRATIN_EXPECTED_DATABASE")
        if expected_database:
            assert health["database"] == expected_database, health
        await checked(client, "POST", "/api/demo/reset")
        scenarios = await checked(client, "GET", "/api/scenarios")
        providers_before = await checked(client, "GET", "/api/providers")
        first = await checked(client, "POST", "/api/opportunities", json=scenarios["urgent"])
        first = await checked(client, "POST", f"/api/opportunities/{first['id']}/run-market")
        first_offer=next(x["offer"] for x in first["match"]["ranked_offers"] if x["offer"]["id"]==first["match"]["recommended_offer_id"])
        assert first_offer["provider_id"] == "nbfc-b", first_offer
        astra = next(x for x in first["match"]["ranked_offers"] if x["offer"]["provider_id"] == "bank-a")
        assert astra["eligible"] is False and len(astra["hard_constraint_failures"]) >= 2, astra
        assert astra["offer"]["status"] == "DECLINE" and astra["offer"]["annual_rate"] is None, astra
        settlement = await checked(client, "POST", f"/api/opportunities/{first['id']}/accept/{first_offer['id']}")
        replay = await checked(client, "POST", f"/api/opportunities/{first['id']}/accept/{first_offer['id']}")
        assert replay["id"] == settlement["id"], (settlement, replay)
        providers_after = await checked(client, "GET", "/api/providers")
        before = next(p for p in providers_before if p["id"] == first_offer["provider_id"])
        after = next(p for p in providers_after if p["id"] == first_offer["provider_id"])
        assert after["available_liquidity"] == before["available_liquidity"] - settlement["amount"]
        assert after["current_exposure"] == before["current_exposure"] + settlement["amount"]
        second = await checked(client, "POST", "/api/opportunities", json=scenarios["strong"])
        second = await checked(client, "POST", f"/api/opportunities/{second['id']}/run-market")
        second_offer=next(x["offer"] for x in second["match"]["ranked_offers"] if x["offer"]["id"]==second["match"]["recommended_offer_id"])
        assert second_offer["provider_id"] == "fund-d", (first_offer,second_offer)
        assert first["integration_status"] == {"invoice_risk":"SERVICE","capital_market":"SERVICE"}
        assert second["integration_status"] == {"invoice_risk":"SERVICE","capital_market":"SERVICE"}
        print(
            f"PASS: {first_offer['provider_name']} -> liquidity update -> "
            f"{second_offer['provider_name']} [{health['database']}]"
        )

if __name__ == "__main__": asyncio.run(main())
