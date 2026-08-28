"""Small explicit SQLite store with JSON payloads and atomic provider updates."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from uuid import uuid4

from contracts.models import AuditEvent, OpportunityRecord, Provider, RiskLedgerEntry, Settlement, utc_now
from .fixtures import providers as fixture_providers

class Store:
    def __init__(self, path: str):
        self.path = path
        self.lock = RLock()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _init(self):
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS opportunities (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS providers (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settlements (id TEXT PRIMARY KEY, opportunity_id TEXT UNIQUE, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit (id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, payload TEXT NOT NULL);
            """)
            if not db.execute("SELECT 1 FROM providers LIMIT 1").fetchone():
                db.executemany("INSERT INTO providers VALUES (?, ?)", [(p.id, p.model_dump_json()) for p in fixture_providers()])

    def reset(self):
        with self.lock, self.connect() as db:
            db.execute("DELETE FROM opportunities"); db.execute("DELETE FROM settlements"); db.execute("DELETE FROM audit"); db.execute("DELETE FROM providers")
            db.executemany("INSERT INTO providers VALUES (?, ?)", [(p.id, p.model_dump_json()) for p in fixture_providers()])

    def save_opportunity(self, item: OpportunityRecord):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO opportunities VALUES (?, ?)", (item.id, item.model_dump_json()))

    def get_opportunity(self, item_id: str) -> OpportunityRecord | None:
        with self.connect() as db: row = db.execute("SELECT payload FROM opportunities WHERE id=?", (item_id,)).fetchone()
        return OpportunityRecord.model_validate_json(row[0]) if row else None

    def opportunities(self) -> list[OpportunityRecord]:
        with self.connect() as db: rows = db.execute("SELECT payload FROM opportunities ORDER BY rowid DESC").fetchall()
        return [OpportunityRecord.model_validate_json(row[0]) for row in rows]

    def providers(self) -> list[Provider]:
        with self.connect() as db: rows = db.execute("SELECT payload FROM providers ORDER BY rowid").fetchall()
        return [Provider.model_validate_json(row[0]) for row in rows]

    def settlement_for(self, opportunity_id: str) -> Settlement | None:
        with self.connect() as db: row = db.execute("SELECT payload FROM settlements WHERE opportunity_id=?", (opportunity_id,)).fetchone()
        return Settlement.model_validate_json(row[0]) if row else None

    def settlements(self) -> list[Settlement]:
        with self.connect() as db: rows = db.execute("SELECT payload FROM settlements ORDER BY rowid DESC").fetchall()
        return [Settlement.model_validate_json(row[0]) for row in rows]

    def settle(self, opportunity: OpportunityRecord, offer_id: str) -> Settlement:
        with self.lock:
            if self.settlement_for(opportunity.id): raise ValueError("Opportunity has already been settled")
            if not opportunity.match or offer_id != opportunity.match.recommended_offer_id: raise ValueError("Only the recommended eligible offer can be accepted")
            ranked = next((r for r in opportunity.match.ranked_offers if r.offer.id == offer_id), None)
            if not ranked or not ranked.eligible or not ranked.offer.financed_amount: raise ValueError("Offer is not eligible")
            provider = next(p for p in self.providers() if p.id == ranked.offer.provider_id)
            amount = ranked.offer.financed_amount
            if provider.available_liquidity < amount: raise ValueError("Provider liquidity changed; rerun the market")
            updated = provider.model_copy(update={"available_liquidity": provider.available_liquidity - amount,
                "current_exposure": provider.current_exposure + amount})
            settlement = Settlement(id="STL-" + uuid4().hex[:10].upper(), opportunity_id=opportunity.id,
                offer_id=offer_id, provider_id=provider.id, amount=amount, settled_at=utc_now())
            opportunity = opportunity.model_copy(update={"status": "SETTLED"})
            with self.connect() as db:
                db.execute("UPDATE providers SET payload=? WHERE id=?", (updated.model_dump_json(), updated.id))
                db.execute("INSERT INTO settlements VALUES (?, ?, ?)", (settlement.id, opportunity.id, settlement.model_dump_json()))
                db.execute("UPDATE opportunities SET payload=? WHERE id=?", (opportunity.model_dump_json(), opportunity.id))
            self.audit("SETTLEMENT_COMPLETED", f"₹{amount:,.0f} simulated allocation settled with {provider.name}; liquidity and exposure updated.", opportunity.id)
            return settlement

    def audit(self, event_type: str, detail: str, opportunity_id: str | None = None):
        event = AuditEvent(id="AUD-" + uuid4().hex[:10].upper(), timestamp=utc_now(), event_type=event_type,
            opportunity_id=opportunity_id, detail=detail)
        with self.connect() as db: db.execute("INSERT INTO audit VALUES (?, ?, ?)", (event.id, event.timestamp.isoformat(), event.model_dump_json()))

    def audits(self) -> list[AuditEvent]:
        with self.connect() as db: rows = db.execute("SELECT payload FROM audit ORDER BY timestamp DESC").fetchall()
        return [AuditEvent.model_validate_json(row[0]) for row in rows]

    def risk_ledger_entries(self) -> list[RiskLedgerEntry]:
        opps = self.opportunities()
        entries: list[RiskLedgerEntry] = []
        for opp in opps:
            if opp.evaluation:
                entries.append(
                    RiskLedgerEntry(
                        id="RSK-" + opp.id.removeprefix("OPP-"),
                        opportunity_id=opp.id,
                        invoice_number=opp.invoice.invoice_number,
                        supplier_name=opp.invoice.supplier_name,
                        buyer_name=opp.invoice.buyer_name,
                        amount=opp.invoice.amount,
                        evaluated_at=opp.created_at,
                        verification=opp.evaluation.verification,
                        risk=opp.evaluation.risk,
                        provenance=opp.evaluation.provenance,
                    )
                )
        return entries

    def risk_ledger_entry(self, identifier: str) -> RiskLedgerEntry | None:
        for entry in self.risk_ledger_entries():
            if entry.id == identifier or entry.opportunity_id == identifier:
                return entry
        return None

