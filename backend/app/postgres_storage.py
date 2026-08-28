"""Supabase Postgres store with row locks and atomic settlement writes."""
from uuid import uuid4

from psycopg import Connection
from psycopg_pool import ConnectionPool

from contracts.models import AuditEvent, OpportunityRecord, Provider, RiskLedgerEntry, Settlement, utc_now
from .fixtures import providers as fixture_providers


def _json(model) -> str:
    return model.model_dump_json()


def _validate(model, payload):
    return model.model_validate(payload) if isinstance(payload, dict) else model.model_validate_json(payload)


class PostgresStore:
    backend = "supabase-postgres"

    def __init__(self, database_url: str):
        self.pool = ConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=5,
            kwargs={"application_name": "pratin-core"},
            open=True,
        )
        self._verify_schema_and_seed()

    def _verify_schema_and_seed(self):
        with self.pool.connection() as db, db.transaction():
            row = db.execute("select to_regclass('pratin.providers')").fetchone()
            if not row or row[0] is None:
                raise RuntimeError(
                    "Supabase schema is missing; apply migration 20260828091405_create_pratin_marketplace"
                )
            if not db.execute("select 1 from pratin.providers limit 1").fetchone():
                self._insert_fixture_providers(db)

    def _insert_fixture_providers(self, db: Connection):
        with db.cursor() as cursor:
            cursor.executemany(
                "insert into pratin.providers (id, payload) values (%s, %s::jsonb)",
                [(provider.id, _json(provider)) for provider in fixture_providers()],
            )

    def reset(self):
        with self.pool.connection() as db, db.transaction():
            db.execute("delete from pratin.audit_events")
            db.execute("delete from pratin.settlements")
            db.execute("delete from pratin.opportunities")
            db.execute("delete from pratin.providers")
            self._insert_fixture_providers(db)

    def save_opportunity(self, item: OpportunityRecord):
        with self.pool.connection() as db, db.transaction():
            result = db.execute(
                """insert into pratin.opportunities as current (id, created_at, status, payload)
                   values (%s, %s, %s, %s::jsonb)
                   on conflict (id) do update set
                     created_at=excluded.created_at,
                     status=excluded.status,
                     payload=excluded.payload
                   where current.status <> 'SETTLED'
                      or excluded.status = 'SETTLED'""",
                (item.id, item.created_at, item.status, _json(item)),
            )
            if result.rowcount == 0:
                raise ValueError("Settled opportunities cannot be overwritten by a stale market run")

    def close(self):
        self.pool.close()

    def get_opportunity(self, item_id: str) -> OpportunityRecord | None:
        with self.pool.connection() as db:
            row = db.execute(
                "select payload from pratin.opportunities where id=%s", (item_id,)
            ).fetchone()
        return _validate(OpportunityRecord, row[0]) if row else None

    def opportunities(self) -> list[OpportunityRecord]:
        with self.pool.connection() as db:
            rows = db.execute(
                "select payload from pratin.opportunities order by created_at desc, id desc"
            ).fetchall()
        return [_validate(OpportunityRecord, row[0]) for row in rows]

    def providers(self) -> list[Provider]:
        with self.pool.connection() as db:
            rows = db.execute("select payload from pratin.providers order by id").fetchall()
        return [_validate(Provider, row[0]) for row in rows]

    def settlement_for(self, opportunity_id: str) -> Settlement | None:
        with self.pool.connection() as db:
            row = db.execute(
                "select payload from pratin.settlements where opportunity_id=%s",
                (opportunity_id,),
            ).fetchone()
        return _validate(Settlement, row[0]) if row else None

    def settlements(self) -> list[Settlement]:
        with self.pool.connection() as db:
            rows = db.execute(
                "select payload from pratin.settlements order by settled_at desc, id desc"
            ).fetchall()
        return [_validate(Settlement, row[0]) for row in rows]

    def settle(self, opportunity: OpportunityRecord, offer_id: str) -> Settlement:
        with self.pool.connection() as db, db.transaction():
            opportunity_row = db.execute(
                "select payload from pratin.opportunities where id=%s for update",
                (opportunity.id,),
            ).fetchone()
            if not opportunity_row:
                raise ValueError("Opportunity no longer exists")

            existing_row = db.execute(
                "select payload from pratin.settlements where opportunity_id=%s",
                (opportunity.id,),
            ).fetchone()
            if existing_row:
                existing = _validate(Settlement, existing_row[0])
                if existing.offer_id == offer_id:
                    return existing
                raise ValueError("Opportunity has already been settled with a different offer")

            current = _validate(OpportunityRecord, opportunity_row[0])
            if not current.match or offer_id != current.match.recommended_offer_id:
                raise ValueError("Only the current recommended eligible offer can be accepted")
            ranked = next((r for r in current.match.ranked_offers if r.offer.id == offer_id), None)
            if not ranked or not ranked.eligible or not ranked.offer.financed_amount:
                raise ValueError("Offer is not eligible")

            provider_row = db.execute(
                "select payload from pratin.providers where id=%s for update",
                (ranked.offer.provider_id,),
            ).fetchone()
            if not provider_row:
                raise ValueError("MARKET_STATE_CHANGED — provider no longer exists; rerun allocation")
            provider = _validate(Provider, provider_row[0])
            amount = ranked.offer.financed_amount
            projected_exposure = provider.current_exposure + amount
            projected_concentration = projected_exposure / provider.portfolio_capacity
            stale_reasons: list[str] = []
            if provider.available_liquidity < amount:
                stale_reasons.append("available liquidity is insufficient")
            if amount > provider.max_ticket_size:
                stale_reasons.append("ticket size limit is exceeded")
            if projected_exposure > provider.portfolio_capacity:
                stale_reasons.append("portfolio capacity is exceeded")
            if projected_concentration > provider.max_concentration_ratio:
                stale_reasons.append("portfolio concentration limit is exceeded")
            if stale_reasons:
                raise ValueError(
                    "MARKET_STATE_CHANGED — " + "; ".join(stale_reasons) + "; rerun allocation"
                )

            updated = provider.model_copy(update={
                "available_liquidity": provider.available_liquidity - amount,
                "current_exposure": projected_exposure,
            })
            settlement = Settlement(
                id="STL-" + uuid4().hex[:10].upper(),
                opportunity_id=current.id,
                offer_id=offer_id,
                provider_id=provider.id,
                amount=amount,
                settled_at=utc_now(),
            )
            settled_opportunity = current.model_copy(update={"status": "SETTLED"})
            event = AuditEvent(
                id="AUD-" + uuid4().hex[:10].upper(),
                timestamp=utc_now(),
                event_type="SETTLEMENT_COMPLETED",
                opportunity_id=current.id,
                detail=(
                    f"₹{amount:,.0f} simulated allocation settled with {provider.name}; "
                    "liquidity and exposure updated."
                ),
            )

            db.execute(
                "update pratin.providers set payload=%s::jsonb where id=%s",
                (_json(updated), updated.id),
            )
            db.execute(
                """insert into pratin.settlements
                   (id, opportunity_id, offer_id, provider_id, settled_at, payload)
                   values (%s, %s, %s, %s, %s, %s::jsonb)""",
                (
                    settlement.id,
                    current.id,
                    offer_id,
                    provider.id,
                    settlement.settled_at,
                    _json(settlement),
                ),
            )
            db.execute(
                "update pratin.opportunities set status=%s, payload=%s::jsonb where id=%s",
                (settled_opportunity.status, _json(settled_opportunity), current.id),
            )
            self._insert_audit(db, event)
            return settlement

    def audit(self, event_type: str, detail: str, opportunity_id: str | None = None):
        event = AuditEvent(
            id="AUD-" + uuid4().hex[:10].upper(),
            timestamp=utc_now(),
            event_type=event_type,
            opportunity_id=opportunity_id,
            detail=detail,
        )
        with self.pool.connection() as db, db.transaction():
            self._insert_audit(db, event)

    def _insert_audit(self, db: Connection, event: AuditEvent):
        db.execute(
            """insert into pratin.audit_events
               (id, timestamp, event_type, opportunity_id, payload)
               values (%s, %s, %s, %s, %s::jsonb)""",
            (
                event.id,
                event.timestamp,
                event.event_type,
                event.opportunity_id,
                _json(event),
            ),
        )

    def audits(self) -> list[AuditEvent]:
        with self.pool.connection() as db:
            rows = db.execute(
                "select payload from pratin.audit_events order by timestamp desc, id desc"
            ).fetchall()
        return [_validate(AuditEvent, row[0]) for row in rows]

    def risk_ledger_entries(self) -> list[RiskLedgerEntry]:
        return [
            RiskLedgerEntry(
                id="RSK-" + opportunity.id.removeprefix("OPP-"),
                opportunity_id=opportunity.id,
                invoice_number=opportunity.invoice.invoice_number,
                supplier_name=opportunity.invoice.supplier_name,
                buyer_name=opportunity.invoice.buyer_name,
                amount=opportunity.invoice.amount,
                evaluated_at=opportunity.created_at,
                verification=opportunity.evaluation.verification,
                risk=opportunity.evaluation.risk,
                provenance=opportunity.evaluation.provenance,
            )
            for opportunity in self.opportunities()
            if opportunity.evaluation
        ]

    def risk_ledger_entry(self, identifier: str) -> RiskLedgerEntry | None:
        return next(
            (
                entry
                for entry in self.risk_ledger_entries()
                if entry.id == identifier or entry.opportunity_id == identifier
            ),
            None,
        )
