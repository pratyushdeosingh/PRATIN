"""Run the canonical two-allocation story against a live required-mode core."""
import asyncio
import httpx

async def main():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",timeout=10) as client:
        assert (await client.get("/health")).json()["mode"] == "required"
        await client.post("/api/demo/reset")
        scenarios=(await client.get("/api/scenarios")).json()
        first=(await client.post("/api/opportunities",json=scenarios["urgent"])).json()
        first=(await client.post(f"/api/opportunities/{first['id']}/run-market")).json()
        first_offer=next(x["offer"] for x in first["match"]["ranked_offers"] if x["offer"]["id"]==first["match"]["recommended_offer_id"])
        assert first_offer["provider_id"] == "nbfc-b", first_offer
        settled=await client.post(f"/api/opportunities/{first['id']}/accept/{first_offer['id']}")
        settled.raise_for_status()
        second=(await client.post("/api/opportunities",json=scenarios["strong"])).json()
        second=(await client.post(f"/api/opportunities/{second['id']}/run-market")).json()
        second_offer=next(x["offer"] for x in second["match"]["ranked_offers"] if x["offer"]["id"]==second["match"]["recommended_offer_id"])
        assert second_offer["provider_id"] != first_offer["provider_id"], (first_offer,second_offer)
        assert first["integration_status"] == {"invoice_risk":"SERVICE","capital_market":"SERVICE"}
        assert second["integration_status"] == {"invoice_risk":"SERVICE","capital_market":"SERVICE"}
        print(f"PASS: {first_offer['provider_name']} -> liquidity update -> {second_offer['provider_name']}")

if __name__ == "__main__": asyncio.run(main())
