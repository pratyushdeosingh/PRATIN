from contextlib import asynccontextmanager
from uuid import uuid4
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from contracts.models import (
    AuditEvent,
    FinancingRequirements,
    Invoice,
    InvoiceEvaluationRequest,
    InvoiceParseResponse,
    MarketRequest,
    MarketTwinRequest,
    OpportunityCreate,
    OpportunityRecord,
    PlatformMetrics,
    Provider,
    RiskLedgerEntry,
    RiskSimulationRequest,
    RiskSimulationResult,
    Settlement,
    StrictModel,
    StrategySimulationRequest,
    VerificationResult,
    utc_now,
)
from .config import Settings
from .fixtures import scenarios
from .matching import rank_offers
from .services import IntegrationClient
from .store_factory import create_store
from .simulation import counterfactual, intelligence, simulate, strategy, stress_lab

settings = Settings(); store = create_store(settings); integrations = IntegrationClient(settings)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    close = getattr(store, "close", None)
    if close:
        close()

app = FastAPI(title="PRATIN Capital Allocation Engine", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
def health(): return {"status": "ok", "service": "pratin-core", "mode": settings.integration_mode, "database": store.backend, "version": "1.0.0"}

@app.get("/api/scenarios")
def demo_scenarios(): return {key: value.model_dump(mode="json") for key, value in scenarios().items()}

@app.post("/api/demo/reset")
def reset(): store.reset(); return {"status": "reset", "notice": "Synthetic marketplace state restored."}

@app.post("/api/opportunities", response_model=OpportunityRecord)
def create_opportunity(request: OpportunityCreate):
    item = OpportunityRecord(id="OPP-" + uuid4().hex[:10].upper(), created_at=utc_now(), status="CREATED",
        invoice=request.invoice, requirements=request.requirements)
    store.save_opportunity(item); store.audit("OPPORTUNITY_CREATED", f"Invoice {request.invoice.invoice_number} entered the market.", item.id)
    return item

@app.post("/api/invoices/parse-pdf", response_model=InvoiceParseResponse)
async def upload_and_parse_invoice_pdf(file: UploadFile = File(...)):
    if not file.filename or not (file.filename.lower().endswith(".pdf") or file.content_type == "application/pdf"):
        raise HTTPException(400, "Only PDF files are supported.")
    pdf_bytes = await file.read()
    if len(pdf_bytes) > 10 * 1024 * 1024:
        raise HTTPException(413, "PDF exceeds maximum allowed size of 10MB.")
    try:
        existing = [opp.invoice for opp in store.opportunities()]
        parsed_resp, status = await integrations.parse_invoice_pdf(
            pdf_bytes, filename=file.filename or "invoice.pdf", existing_invoices=existing
        )
    except Exception as exc:
        raise HTTPException(503, f"Invoice risk service unavailable: {exc}") from exc
    if parsed_resp.status in ("PDF_EMPTY", "PDF_INVALID"):
        raise HTTPException(400, parsed_resp.error_detail or parsed_resp.status)
    if parsed_resp.status == "PDF_TEXT_UNREADABLE":
        return JSONResponse(status_code=422, content=parsed_resp.model_dump(mode="json"))

    if parsed_resp.invoice and parsed_resp.evaluation:
        opp_id = "OPP-" + uuid4().hex[:10].upper()
        reqs = FinancingRequirements(
            minimum_amount=round(parsed_resp.invoice.amount * 0.8, 0),
            max_settlement_hours=48,
            desired_tenor_days=60,
        )
        item = OpportunityRecord(
            id=opp_id,
            created_at=utc_now(),
            status="CREATED",
            invoice=parsed_resp.invoice,
            requirements=reqs,
            evaluation=parsed_resp.evaluation,
            integration_status={"invoice_risk": status, "capital_market": "UNAVAILABLE"},
        )
        store.save_opportunity(item)
        if parsed_resp.extracted_fields:
            store.audit("PDF_INVOICE_PARSED", f"Parsed PDF {file.filename} (Confidence: {parsed_resp.extracted_fields.extraction_confidence.value}) for invoice {parsed_resp.invoice.invoice_number}.", opp_id)
        store.audit("RISK_EVALUATED", f"PDF invoice {parsed_resp.invoice.invoice_number} evaluated with {parsed_resp.evaluation.risk.band.value} risk ({parsed_resp.evaluation.risk.score}/100).", opp_id)
        if parsed_resp.ledger_entry:
            parsed_resp.ledger_entry = parsed_resp.ledger_entry.model_copy(update={"opportunity_id": opp_id})
    return parsed_resp

@app.get("/api/opportunities", response_model=list[OpportunityRecord])
def list_opportunities(): return store.opportunities()

@app.get("/api/opportunities/{item_id}", response_model=OpportunityRecord)
def get_opportunity(item_id: str):
    item = store.get_opportunity(item_id)
    if not item: raise HTTPException(404, "Opportunity not found")
    return item

async def clear_market(item_id: str, requirements: FinancingRequirements | None = None) -> OpportunityRecord:
    """Run the reusable backend-owned allocation workflow for one opportunity."""
    item = store.get_opportunity(item_id)
    if not item: raise HTTPException(404, "Opportunity not found")
    if item.status == "SETTLED": raise HTTPException(409, "Settled opportunities cannot be rerun")
    if requirements:
        item = item.model_copy(update={"requirements": requirements})
    try:
        existing = [opp.invoice for opp in store.opportunities() if opp.id != item.id]
        evaluation, risk_status = await integrations.invoice_evaluation(
            InvoiceEvaluationRequest(invoice=item.invoice, existing_invoices=existing)
        )
        providers = store.providers()
        market, market_status = await integrations.market(MarketRequest(opportunity_id=item.id, invoice=item.invoice,
            requirements=item.requirements, verification=evaluation.verification, risk=evaluation.risk, providers=providers))
    except Exception as exc: raise HTTPException(503, f"Required integration unavailable: {exc}") from exc
    decision = rank_offers(item.id, item.requirements, evaluation.risk, market.offers,
                           {provider.id: provider.available_liquidity for provider in providers})
    item = item.model_copy(update={"status": "MARKET_RUN", "evaluation": evaluation, "offers": market.offers,
        "match": decision, "integration_status": {"invoice_risk": risk_status, "capital_market": market_status}})
    try:
        store.save_opportunity(item)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    store.audit("RISK_EVALUATED", f"Invoice {item.invoice.invoice_number} verified ({evaluation.verification.status.value}) with {evaluation.risk.band.value} risk score {evaluation.risk.score}/100.", item.id)
    store.audit("MARKET_CLEARED", f"{len(market.offers)} providers evaluated; recommendation {decision.recommended_offer_id or 'none'} under {item.requirements.priority} priority.", item.id)
    return item

@app.post("/api/opportunities/{item_id}/run-market", response_model=OpportunityRecord)
async def run_market(item_id: str, requirements: FinancingRequirements | None = None):
    return await clear_market(item_id, requirements)

@app.post("/api/opportunities/{item_id}/accept/{offer_id}", response_model=Settlement)
def accept(item_id: str, offer_id: str):
    item = store.get_opportunity(item_id)
    if not item: raise HTTPException(404, "Opportunity not found")
    try: return store.settle(item, offer_id)
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc

@app.get("/api/providers", response_model=list[Provider])
def get_providers(): return store.providers()

@app.get("/api/settlements", response_model=list[Settlement])
def get_settlements(): return store.settlements()

@app.get("/api/audit", response_model=list[AuditEvent])
def get_audit(): return store.audits()

@app.get("/api/risk-ledger", response_model=list[RiskLedgerEntry])
def list_risk_ledger():
    return store.risk_ledger_entries()

@app.get("/api/risk-ledger/{item_id}", response_model=RiskLedgerEntry)
def get_risk_ledger_entry(item_id: str):
    entry = store.risk_ledger_entry(item_id)
    if not entry:
        raise HTTPException(404, "Risk ledger entry not found")
    return entry

def _entry_invoice(entry: RiskLedgerEntry):
    if entry.opportunity_id:
        opp = store.get_opportunity(entry.opportunity_id)
        if opp:
            return opp.invoice
    from contracts.models import Invoice
    return Invoice(
        invoice_number=entry.invoice_number,
        supplier_name=entry.supplier_name,
        buyer_name=entry.buyer_name,
        amount=entry.amount,
    )

@app.get("/api/risk-ledger/{item_id}/what-if-scenarios", response_model=list[RiskSimulationResult])
def get_what_if_scenarios(item_id: str):
    entry = store.risk_ledger_entry(item_id)
    if not entry:
        raise HTTPException(404, "Risk ledger entry not found")
    inv = _entry_invoice(entry)
    from services.invoice_risk.engine import get_standard_what_if_scenarios
    return get_standard_what_if_scenarios(inv, entry.verification)

@app.post("/api/risk-ledger/{item_id}/simulate", response_model=RiskSimulationResult)
def simulate_risk_for_entry(item_id: str, request: RiskSimulationRequest):
    entry = store.risk_ledger_entry(item_id)
    if not entry:
        raise HTTPException(404, "Risk ledger entry not found")
    inv = _entry_invoice(entry)
    from services.invoice_risk.engine import simulate_risk_change
    return simulate_risk_change(inv, entry.verification, request)

class InvoiceSimulationPayload(StrictModel):
    invoice: Invoice
    verification: VerificationResult
    simulation: RiskSimulationRequest

@app.post("/api/invoices/simulate-risk", response_model=RiskSimulationResult)
def simulate_invoice_risk(payload: InvoiceSimulationPayload):
    from services.invoice_risk.engine import simulate_risk_change
    return simulate_risk_change(payload.invoice, payload.verification, payload.simulation)

@app.get("/api/platform/metrics", response_model=PlatformMetrics)
def metrics():
    providers = store.providers(); opportunities = store.opportunities(); settlements = store.settlements()
    offers = [offer for item in opportunities for offer in item.offers if offer.status == "OFFER"]
    participating = len({offer.provider_id for offer in offers})
    return PlatformMetrics(available_liquidity=sum(p.available_liquidity for p in providers),
        active_opportunities=sum(i.status != "SETTLED" for i in opportunities), offers_generated=len(offers),
        financing_allocated=sum(s.amount for s in settlements), settlements=len(settlements),
        provider_participation_rate=round(participating / max(len(providers), 1), 2))

def _simulation_opportunity(item_id: str) -> OpportunityRecord:
    item = store.get_opportunity(item_id)
    if not item: raise HTTPException(404, "Opportunity not found")
    if not item.match or not item.evaluation: raise HTTPException(409, "Run the market before using simulations")
    return item

@app.post("/api/simulations/market-twin")
def market_twin(request: MarketTwinRequest):
    if not settings.enable_digital_twin: raise HTTPException(404, "Digital Twin is disabled")
    try: return simulate(_simulation_opportunity(request.opportunity_id), store.providers(), request.overrides)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc

@app.get("/api/opportunities/{item_id}/counterfactual/{provider_id}")
def why_not_provider(item_id: str, provider_id: str):
    try: return counterfactual(_simulation_opportunity(item_id), store.providers(), provider_id)
    except LookupError as exc: raise HTTPException(404, str(exc)) from exc

@app.post("/api/simulations/strategy")
def supplier_strategy(request: StrategySimulationRequest):
    try: return strategy(_simulation_opportunity(request.opportunity_id), store.providers(), request)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc

@app.post("/api/simulations/stress/{item_id}")
def run_stress_lab(item_id: str):
    if not settings.enable_stress_lab: raise HTTPException(404, "Stress Lab is disabled")
    return stress_lab(_simulation_opportunity(item_id), store.providers())

@app.get("/api/market/intelligence")
def market_intelligence(): return intelligence(store.providers(), store.opportunities())
