"""Postgres settlement parity checks; exercised by the required-mode CI job."""
from concurrent.futures import ThreadPoolExecutor
import os

import pytest

from backend.app.postgres_storage import PostgresStore, _json
from backend.tests.test_settlement import ready_opportunity


DATABASE_URL = os.getenv("PRATIN_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="PRATIN_TEST_POSTGRES_URL is required for Postgres settlement parity tests",
)


@pytest.fixture
def store():
    instance = PostgresStore(DATABASE_URL)
    instance.reset()
    try:
        yield instance
    finally:
        instance.close()


def update_provider(store: PostgresStore, provider):
    with store.pool.connection() as db, db.transaction():
        db.execute(
            "update pratin.providers set payload=%s::jsonb where id=%s",
            (_json(provider), provider.id),
        )


def test_postgres_schema_keeps_browser_roles_out(store):
    with store.pool.connection() as db:
        for role in ("anon", "authenticated"):
            privileges = db.execute(
                """select has_schema_privilege(%s, 'pratin', 'USAGE'),
                          has_table_privilege(%s, 'pratin.opportunities', 'SELECT')""",
                (role, role),
            ).fetchone()
            assert privileges == (False, False)
        assert db.execute(
            "select has_schema_privilege('service_role', 'pratin', 'USAGE')"
        ).fetchone() == (True,)
        rls_tables = db.execute(
            """select count(*) from pg_class c
               join pg_namespace n on n.oid=c.relnamespace
               where n.nspname='pratin' and c.relkind='r' and c.relrowsecurity"""
        ).fetchone()[0]
        assert rls_tables == 4


def test_postgres_duplicate_acceptance_mutates_and_audits_once(store):
    item = ready_opportunity(store)
    offer_id = item.match.recommended_offer_id
    provider_id = next(r.offer.provider_id for r in item.match.ranked_offers if r.offer.id == offer_id)
    before = next(provider for provider in store.providers() if provider.id == provider_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        settlements = list(pool.map(lambda _: store.settle(item, offer_id), range(2)))

    after = next(provider for provider in store.providers() if provider.id == provider_id)
    assert settlements[0].id == settlements[1].id
    assert len(store.settlements()) == 1
    assert after.available_liquidity == before.available_liquidity - settlements[0].amount
    assert after.current_exposure == before.current_exposure + settlements[0].amount
    assert [event.event_type for event in store.audits()] == ["SETTLEMENT_COMPLETED"]

    different_offer = next(r.offer.id for r in item.match.ranked_offers if r.offer.id != offer_id)
    with pytest.raises(ValueError, match="different offer"):
        store.settle(item, different_offer)


@pytest.mark.parametrize("condition", ["liquidity", "capacity", "concentration"])
def test_postgres_rejects_stale_provider_state_without_partial_writes(store, condition):
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
    assert store.get_opportunity(item.id).status == "MARKET_RUN"
    assert store.audits() == []


def test_postgres_rolls_back_and_rejects_stale_market_overwrite(store, monkeypatch):
    item = ready_opportunity(store)
    offer_id = item.match.recommended_offer_id
    provider_id = next(r.offer.provider_id for r in item.match.ranked_offers if r.offer.id == offer_id)
    before = next(provider for provider in store.providers() if provider.id == provider_id)
    original_insert_audit = store._insert_audit

    def fail_audit(_db, _event):
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(store, "_insert_audit", fail_audit)
    with pytest.raises(RuntimeError, match="simulated audit failure"):
        store.settle(item, offer_id)
    monkeypatch.setattr(store, "_insert_audit", original_insert_audit)

    assert next(provider for provider in store.providers() if provider.id == provider_id) == before
    assert store.settlements() == []
    settlement = store.settle(item, offer_id)
    assert settlement
    with pytest.raises(ValueError, match="stale market run"):
        store.save_opportunity(item)
    assert store.get_opportunity(item.id).status == "SETTLED"
