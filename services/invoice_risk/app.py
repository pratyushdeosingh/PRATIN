from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from contracts.models import (
    InvoiceEvaluation,
    InvoiceEvaluationRequest,
    InvoiceParseResponse,
    RiskAssessment,
    RiskLedgerEntry,
    VerificationResult,
)
from .engine import assess_risk, create_risk_ledger_entry, evaluate, verify_invoice
from .pdf_parser import parse_and_evaluate_pdf

app = FastAPI(title="PRATIN Invoice & Risk Agent", version="1.0.0")

@app.get("/health")
def health(): return {"status": "ok", "service": "invoice-risk", "version": "1.0.0"}

@app.post("/verify", response_model=VerificationResult)
def verify(request: InvoiceEvaluationRequest): return verify_invoice(request.invoice)

@app.post("/evaluate", response_model=InvoiceEvaluation)
def evaluate_endpoint(request: InvoiceEvaluationRequest): return evaluate(request.invoice)

@app.post("/ledger-entry", response_model=RiskLedgerEntry)
def ledger_entry_endpoint(request: InvoiceEvaluationRequest): return create_risk_ledger_entry(request.invoice)

@app.post("/parse-invoice", response_model=InvoiceParseResponse)
async def parse_invoice_endpoint(file: UploadFile = File(...)):
    if not file.filename or not (file.filename.lower().endswith(".pdf") or file.content_type == "application/pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    pdf_bytes = await file.read()
    if len(pdf_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="PDF exceeds maximum allowed size of 10MB.")
    result = parse_and_evaluate_pdf(pdf_bytes, filename=file.filename or "invoice.pdf")
    if result.status in ("PDF_EMPTY", "PDF_INVALID"):
        raise HTTPException(status_code=400, detail=result.error_detail or result.status)
    if result.status == "PDF_TEXT_UNREADABLE":
        return JSONResponse(status_code=422, content=result.model_dump(mode="json"))
    return result

