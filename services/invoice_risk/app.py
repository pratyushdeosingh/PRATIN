from fastapi import FastAPI
from contracts.models import InvoiceEvaluation, InvoiceEvaluationRequest, RiskAssessment, RiskLedgerEntry, VerificationResult
from .engine import assess_risk, create_risk_ledger_entry, evaluate, verify_invoice

app = FastAPI(title="PRATIN Invoice & Risk Agent", version="1.0.0")

@app.get("/health")
def health(): return {"status": "ok", "service": "invoice-risk", "version": "1.0.0"}

@app.post("/verify", response_model=VerificationResult)
def verify(request: InvoiceEvaluationRequest): return verify_invoice(request.invoice)

@app.post("/evaluate", response_model=InvoiceEvaluation)
def evaluate_endpoint(request: InvoiceEvaluationRequest): return evaluate(request.invoice)

@app.post("/ledger-entry", response_model=RiskLedgerEntry)
def ledger_entry_endpoint(request: InvoiceEvaluationRequest): return create_risk_ledger_entry(request.invoice)

