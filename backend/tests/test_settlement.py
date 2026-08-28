from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.app.fixtures import scenarios
from backend.app.matching import rank_offers
from backend.app.storage import Store
from contracts.models import OpportunityRecord, Provider, utc_now
from services.capital_market.engine import generate_market
from services.invoice_risk.engine import evaluate
from contracts.models import MarketRequest


def ready_opportunity(store: Store, scenario_name="urgent"):
    scenario = scenarios()[scenario_name]
    item = OpportunityRecord(
        id=f"OPP-{scenario_name.upper()}",
        created_at=utc_now(),
        status="CREATED",
        invoice=scenario.invoice,
        requirements=scenario.requirements,
    )
    evaluation = evaluate(item.invoice)
    providers = store.providers()
    market = generate_market(MarketRequest(
        opportunity_id=item.id,
        invoice=item.invoice,
        requirements=item.requirements,
        verification=evaluation.verification,
        risk=evaluation.risk,
        providers=providers,
    ))
    decision = rank_offers(
        item.id,
        item.requirements,
        evaluation.risk,
        market.offers,
        {provider.id: provider.available_liquidity for provider in providers},
    )
    item = item.model_copy(update={
        "status": "MARKET_RUN",
        "evaluation": evaluation,
        "offers": market.offers,
        "match": decision,
    })
    store.save_opportunity(item)
    return item


def update_provider(store: Store, provider: Provider):
    with store.connect() as db:
        db.execute("UPDATE providers SET payload=? WHERE id=?", (provider.model_dump_json(), provider.id))


def test_duplicate_and_concurrent_acceptance_replays_once(tmp_path):
    store = Store(str(tmp_path / "market.db"))
    item = ready_opportunity(store)
    offer_id = item.match.recommended_offer_id
    provider_id = next(r.offer.provider_id for r in item.match.ranked_offers if r.offer.id == offer_id)
    before = next(p for p in store.providers() if p.id == provider_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        settlements = list(pool.map(lambda _: store.settle(item, offer_id), range(2)))
    after = next(p for p in store.providers() if p.id == provider_id)
    assert settlements[0].id == settlements[1].id
    assert len(store.settlements()) == 1
    assert after.available_liquidity == before.available_liquidity - settlements[0].amount
    assert after.current_exposure == before.current_exposure + settlements[0].amount
    assert [event.event_type for event in store.audits()] == ["SETTLEMENT_COMPLETED"]


@pytest.mark.parametrize("condition", ["liquidity", "capacity", "concentration"])
def test_mutable_provider_state_invalidates_stale_recommendation(tmp_path, condition):
    store = Store(str(tmp_path / f"{condition}.db"))
    item = ready_opportunity(store)
    offer_id = item.match.recommended_offer_id
    ranked = next(r for r in item.match.ranked_offers if r.offer.id == offer_id)
    provider = next(p for p in store.providers() if p.id == ranked.offer.provider_id)
    amount = ranked.offer.financed_amount
    if condition == "liquidity":
        provider = provider.model_copy(update={"available_liquidity": amount - 1})
    elif condition == "capacity":
        provider = provider.model_copy(update={"current_exposure": provider.portfolio_capacity - amount + 1})
    else:
        provider = provider.model_copy(update={
            "current_exposure": provider.portfolio_capacity * provider.max_concentration_ratio - amount + 1
        })
    update_provider(store, provider)
    with pytest.raises(ValueError, match="MARKET_STATE_CHANGED"):
        store.settle(item, offer_id)
    assert store.settlements() == []


def test_non_recommended_and_ineligible_offers_cannot_settle(tmp_path):
    store = Store(str(tmp_path / "eligibility.db"))
    item = ready_opportunity(store)
    ineligible = next(r for r in item.match.ranked_offers if not r.eligible)
    with pytest.raises(ValueError, match="recommended"):
        store.settle(item, ineligible.offer.id)
    other_eligible = next(r for r in item.match.ranked_offers if r.eligible and r.rank != 1)
    with pytest.raises(ValueError, match="recommended"):
        store.settle(item, other_eligible.offer.id)


def test_settlement_rolls_back_every_write_when_audit_fails(tmp_path, monkeypatch):
    store = Store(str(tmp_path / "rollback.db"))
    item = ready_opportunity(store)
    offer_id = item.match.recommended_offer_id
    provider_id = next(r.offer.provider_id for r in item.match.ranked_offers if r.offer.id == offer_id)
    before = next(p for p in store.providers() if p.id == provider_id)

    def fail_audit(_db, _event):
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(store, "_insert_audit", fail_audit)
    with pytest.raises(RuntimeError, match="simulated audit failure"):
        store.settle(item, offer_id)
    after = next(p for p in store.providers() if p.id == provider_id)
    assert after == before
    assert store.settlements() == []
    assert store.get_opportunity(item.id).status == "MARKET_RUN"
    assert store.audits() == []


def test_stale_market_result_cannot_overwrite_settled_opportunity(tmp_path):
    store = Store(str(tmp_path / "stale-market.db"))
    item = ready_opportunity(store)
    store.settle(item, item.match.recommended_offer_id)

    with pytest.raises(ValueError, match="stale market run"):
        store.save_opportunity(item)

    assert store.get_opportunity(item.id).status == "SETTLED"
    assert len(store.settlements()) == 1
