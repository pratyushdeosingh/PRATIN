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
    backend = "sqlite"

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
        except Exception:
            connection.rollback()
            raise
        else:
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
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing_row = db.execute(
                "SELECT payload FROM settlements WHERE opportunity_id=?", (opportunity.id,)
            ).fetchone()
            if existing_row:
                existing = Settlement.model_validate_json(existing_row[0])
                if existing.offer_id == offer_id:
                    return existing
                raise ValueError("Opportunity has already been settled with a different offer")

            opportunity_row = db.execute(
                "SELECT payload FROM opportunities WHERE id=?", (opportunity.id,)
            ).fetchone()
            if not opportunity_row:
                raise ValueError("Opportunity no longer exists")
            current = OpportunityRecord.model_validate_json(opportunity_row[0])
            if not current.match or offer_id != current.match.recommended_offer_id:
                raise ValueError("Only the current recommended eligible offer can be accepted")
            ranked = next((r for r in current.match.ranked_offers if r.offer.id == offer_id), None)
            if not ranked or not ranked.eligible or not ranked.offer.financed_amount:
                raise ValueError("Offer is not eligible")

            provider_row = db.execute(
                "SELECT payload FROM providers WHERE id=?", (ranked.offer.provider_id,)
            ).fetchone()
            if not provider_row:
                raise ValueError("MARKET_STATE_CHANGED — provider no longer exists; rerun allocation")
            provider = Provider.model_validate_json(provider_row[0])
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
            db.execute("UPDATE providers SET payload=? WHERE id=?", (updated.model_dump_json(), updated.id))
            db.execute(
                "INSERT INTO settlements VALUES (?, ?, ?)",
                (settlement.id, current.id, settlement.model_dump_json()),
            )
            db.execute(
                "UPDATE opportunities SET payload=? WHERE id=?",
                (settled_opportunity.model_dump_json(), current.id),
            )
            self._insert_audit(db, event)
            return settlement

    def audit(self, event_type: str, detail: str, opportunity_id: str | None = None):
        event = AuditEvent(id="AUD-" + uuid4().hex[:10].upper(), timestamp=utc_now(), event_type=event_type,
            opportunity_id=opportunity_id, detail=detail)
        with self.connect() as db:
            self._insert_audit(db, event)

    def _insert_audit(self, db: sqlite3.Connection, event: AuditEvent):
        db.execute(
            "INSERT INTO audit VALUES (?, ?, ?)",
            (event.id, event.timestamp.isoformat(), event.model_dump_json()),
        )

    def audits(self) -> list[AuditEvent]:
        with self.connect() as db: rows = db.execute("SELECT payload FROM audit ORDER BY timestamp DESC").fetchall()
        return [AuditEvent.model_validate_json(row[0]) for row in rows]
    def risk_ledger_entries(self) -> list[RiskLedgerEntry]:
        opps = self.opportunities()
        audits = self.audits()
        pdf_audit_map: dict[str, str] = {
            a.opportunity_id: a.detail
            for a in audits
            if a.opportunity_id and a.event_type == "PDF_INVOICE_PARSED"
        }
        entries: list[RiskLedgerEntry] = []
        for opp in opps:
            if opp.evaluation:
                is_pdf = opp.id in pdf_audit_map
                filename = None
                if is_pdf:
                    import re
                    m = re.search(r'Parsed PDF ([^\s]+)', pdf_audit_map[opp.id])
                    filename = m.group(1) if m else "invoice.pdf"
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
                        source="PDF_UPLOAD" if is_pdf else "SCENARIO",
                        source_filename=filename,
                    )
                )
        return entries

    def risk_ledger_entry(self, identifier: str) -> RiskLedgerEntry | None:
        for entry in self.risk_ledger_entries():
            if entry.id == identifier or entry.opportunity_id == identifier:
                return entry
        return None
