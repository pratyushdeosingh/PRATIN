import json
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from contracts.models import (
    Invoice,
    InvoiceEvaluation,
    InvoiceEvaluationRequest,
    InvoiceParseResponse,
    RiskAssessment,
    RiskLedgerEntry,
    RiskSimulationRequest,
    RiskSimulationResult,
    VerificationResult,
)
from .engine import (
    assess_risk,
    create_risk_ledger_entry,
    evaluate,
    get_standard_what_if_scenarios,
    simulate_risk_change,
    verify_invoice,
)
from .pdf_parser import parse_and_evaluate_pdf

app = FastAPI(title="PRATIN Invoice & Risk Agent", version="1.0.0")

@app.get("/health")
def health(): return {"status": "ok", "service": "invoice-risk", "version": "1.0.0"}

@app.post("/verify", response_model=VerificationResult)
def verify(request: InvoiceEvaluationRequest): return verify_invoice(request.invoice, request.existing_invoices)

@app.post("/evaluate", response_model=InvoiceEvaluation)
def evaluate_endpoint(request: InvoiceEvaluationRequest): return evaluate(request.invoice, request.existing_invoices)

@app.post("/ledger-entry", response_model=RiskLedgerEntry)
def ledger_entry_endpoint(request: InvoiceEvaluationRequest): return create_risk_ledger_entry(request.invoice, existing_invoices=request.existing_invoices)

@app.post("/parse-invoice", response_model=InvoiceParseResponse)
async def parse_invoice_endpoint(
    file: UploadFile = File(...),
    existing_invoices: str | None = Form(None),
):
    if not file.filename or not (file.filename.lower().endswith(".pdf") or file.content_type == "application/pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    pdf_bytes = await file.read()
    if len(pdf_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="PDF exceeds maximum allowed size of 10MB.")
    parsed_existing: list[Invoice] | None = None
    if existing_invoices:
        try:
            raw_list = json.loads(existing_invoices)
            parsed_existing = [Invoice.model_validate(item) for item in raw_list]
        except Exception:
            parsed_existing = None
    result = parse_and_evaluate_pdf(
        pdf_bytes, filename=file.filename or "invoice.pdf", existing_invoices=parsed_existing
    )
    if result.status in ("PDF_EMPTY", "PDF_INVALID"):
        raise HTTPException(status_code=400, detail=result.error_detail or result.status)
    if result.status == "PDF_TEXT_UNREADABLE":
        return JSONResponse(status_code=422, content=result.model_dump(mode="json"))
    return result


class RiskSimulationEndpointRequest(BaseModel):
    invoice: Invoice
    verification: VerificationResult
    simulation: RiskSimulationRequest


class WhatIfScenariosEndpointRequest(BaseModel):
    invoice: Invoice
    verification: VerificationResult


@app.post("/simulate-risk", response_model=RiskSimulationResult)
def simulate_risk_endpoint(request: RiskSimulationEndpointRequest):
    return simulate_risk_change(request.invoice, request.verification, request.simulation)


@app.post("/what-if-scenarios", response_model=list[RiskSimulationResult])
def what_if_scenarios_endpoint(request: WhatIfScenariosEndpointRequest):
    return get_standard_what_if_scenarios(request.invoice, request.verification)

