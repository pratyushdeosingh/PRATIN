from datetime import date, timedelta
from fastapi.testclient import TestClient
from contracts.models import Invoice, RiskBand, VerificationStatus
from services.invoice_risk.app import app
from services.invoice_risk.engine import create_risk_ledger_entry, evaluate, verify_invoice

client = TestClient(app)

def invoice(**changes):
    values=dict(invoice_number="INV-101",supplier_name="Supplier",buyer_name="Buyer",amount=1_000_000,
        issue_date=date.today()-timedelta(days=5),due_date=date.today()+timedelta(days=55),industry="Manufacturing",
        gstin="27ABCDE1234F1Z5",purchase_order_reference="PO-1",buyer_rating=.9,supplier_history_months=36,
        on_time_payment_ratio=.95,prior_defaults=0)
    values.update(changes); return Invoice(**values)

def test_strong_invoice_scores_better_than_risky_invoice():
    strong=evaluate(invoice()); risky=evaluate(invoice(gstin=None,purchase_order_reference=None,buyer_rating=.3,
        supplier_history_months=4,on_time_payment_ratio=.5,prior_defaults=2))
    assert strong.risk.score < risky.risk.score
    assert risky.risk.missing_information == ["gstin","purchase_order_reference"]

def test_invalid_gstin_is_not_verified():
    assert verify_invoice(invoice(gstin="INVALID")).status == VerificationStatus.REJECTED

def test_past_due_date_invoice_is_rejected():
    inv = invoice(due_date=date.today() - timedelta(days=1))
    result = verify_invoice(inv)
    assert result.status == VerificationStatus.REJECTED
    assert "Invoice is already past its due date." in result.reasons

def test_incomplete_invoice_retains_explicit_uncertainty():
    inv = invoice(gstin=None, purchase_order_reference=None)
    eval_result = evaluate(inv)
    assert eval_result.verification.status == VerificationStatus.PARTIALLY_VERIFIED
    assert set(eval_result.verification.uncertain_fields) == {"gstin", "purchase_order_reference"}
    assert "gstin" in eval_result.risk.missing_information
    uncertainty_factor = next((f for f in eval_result.risk.factors if f.label == "Verification uncertainty"), None)
    assert uncertainty_factor is not None
    assert uncertainty_factor.impact == "negative"
    assert uncertainty_factor.points > 0

def test_risk_ledger_entry_creation_and_factor_explainability():
    inv = invoice()
    entry = create_risk_ledger_entry(inv, opportunity_id="OPP-TEST-1")
    assert entry.id.startswith("RSK-")
    assert entry.opportunity_id == "OPP-TEST-1"
    assert entry.invoice_number == "INV-101"
    assert entry.supplier_name == "Supplier"
    assert entry.buyer_name == "Buyer"
    assert entry.amount == 1_000_000
    assert entry.verification.status == VerificationStatus.VERIFIED
    assert entry.risk.band in [RiskBand.LOW, RiskBand.MODERATE]
    assert len(entry.risk.factors) > 0
    # Every factor has label, impact, points, and non-empty explanation
    for f in entry.risk.factors:
        assert f.label
        assert f.impact in ["positive", "negative", "neutral"]
        assert isinstance(f.points, float) or isinstance(f.points, int)
        assert len(f.explanation) > 0

def test_invoice_risk_service_endpoints():
    inv_data = invoice().model_dump(mode="json")
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    verify_resp = client.post("/verify", json={"invoice": inv_data})
    assert verify_resp.status_code == 200
    assert verify_resp.json()["status"] == "VERIFIED"
    eval_resp = client.post("/evaluate", json={"invoice": inv_data})
    assert eval_resp.status_code == 200
    assert "verification" in eval_resp.json() and "risk" in eval_resp.json()
    ledger_resp = client.post("/ledger-entry", json={"invoice": inv_data})
    assert ledger_resp.status_code == 200
    assert ledger_resp.json()["invoice_number"] == "INV-101"

