from datetime import date, timedelta
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from contracts.models import Invoice, RiskBand, VerificationStatus
from services.invoice_risk.app import app
from services.invoice_risk.engine import assess_risk, create_risk_ledger_entry, evaluate, verify_invoice

client = TestClient(app)

def invoice(**changes):
    values = dict(
        invoice_number="INV-101",
        supplier_name="Supplier",
        buyer_name="Buyer",
        amount=1_000_000,
        issue_date=date.today() - timedelta(days=5),
        due_date=date.today() + timedelta(days=55),
        industry="Manufacturing",
        gstin="27ABCDE1234F1Z5",
        purchase_order_reference="PO-1",
        buyer_rating=0.9,
        supplier_history_months=36,
        on_time_payment_ratio=0.95,
        prior_defaults=0,
    )
    values.update(changes)
    return Invoice(**values)

def test_strong_invoice_scores_better_than_risky_invoice():
    strong = evaluate(invoice())
    risky = evaluate(invoice(
        gstin=None,
        purchase_order_reference=None,
        buyer_rating=0.3,
        supplier_history_months=4,
        on_time_payment_ratio=0.5,
        prior_defaults=2,
    ))
    assert strong.risk.score < risky.risk.score
    assert risky.risk.missing_information == ["gstin", "purchase_order_reference"]

def test_graduated_payment_history_scoring():
    # >=95% -> -15, 90-94.99% -> -10, 85-89.99% -> -5, 70-84.99% -> +5, 50-69.99% -> +12, <50% -> +20
    test_cases = [
        (0.96, -15.0, "PAYMENT_HISTORY_STRONG"),
        (0.95, -15.0, "PAYMENT_HISTORY_STRONG"),
        (0.92, -10.0, "PAYMENT_HISTORY_STRONG"),
        (0.90, -10.0, "PAYMENT_HISTORY_STRONG"),
        (0.88, -5.0, "PAYMENT_HISTORY_STRONG"),
        (0.85, -5.0, "PAYMENT_HISTORY_STRONG"),
        (0.84, 5.0, "PAYMENT_HISTORY_WEAK"),
        (0.70, 5.0, "PAYMENT_HISTORY_WEAK"),
        (0.60, 12.0, "PAYMENT_HISTORY_WEAK"),
        (0.50, 12.0, "PAYMENT_HISTORY_WEAK"),
        (0.40, 20.0, "PAYMENT_HISTORY_CRITICAL"),
        (0.20, 20.0, "PAYMENT_HISTORY_CRITICAL"),
    ]
    for ratio, expected_pts, expected_code in test_cases:
        inv = invoice(on_time_payment_ratio=ratio)
        eval_res = evaluate(inv)
        f = next(f for f in eval_res.risk.factors if f.label == "Payment history")
        assert f.points == expected_pts, f"Failed for ratio {ratio}"
        assert f.reason_code == expected_code

def test_graduated_supplier_history_scoring():
    # <6 -> +12, 6-11 -> +8, 12-23 -> +3, 24-35 -> -5, >=36 -> -8
    test_cases = [
        (2, 12.0, "SUPPLIER_MATURITY_NEW"),
        (5, 12.0, "SUPPLIER_MATURITY_NEW"),
        (6, 8.0, "SUPPLIER_MATURITY_WEAK"),
        (11, 8.0, "SUPPLIER_MATURITY_WEAK"),
        (12, 3.0, "SUPPLIER_MATURITY_WEAK"),
        (23, 3.0, "SUPPLIER_MATURITY_WEAK"),
        (24, -5.0, "SUPPLIER_MATURITY_STRONG"),
        (35, -5.0, "SUPPLIER_MATURITY_STRONG"),
        (36, -8.0, "SUPPLIER_MATURITY_STRONG"),
        (60, -8.0, "SUPPLIER_MATURITY_STRONG"),
    ]
    for months, expected_pts, expected_code in test_cases:
        inv = invoice(supplier_history_months=months)
        eval_res = evaluate(inv)
        f = next(f for f in eval_res.risk.factors if f.label == "Supplier operating history")
        assert f.points == expected_pts, f"Failed for months {months}"
        assert f.reason_code == expected_code

def test_graduated_concentration_scoring():
    # <10L -> 0, 10-24.99L -> +2, 25-49.99L -> +4, 50-99.99L -> +8, >=1Cr -> +12
    test_cases = [
        (500_000, 0.0),
        (999_999, 0.0),
        (1_000_000, 2.0),
        (2_499_999, 2.0),
        (2_500_000, 4.0),
        (4_999_999, 4.0),
        (5_000_000, 8.0),
        (9_999_999, 8.0),
        (10_000_000, 12.0),
        (50_000_000, 12.0),
    ]
    for amt, expected_pts in test_cases:
        inv = invoice(amount=amt)
        eval_res = evaluate(inv)
        f = next((f for f in eval_res.risk.factors if f.label == "Large ticket"), None)
        if expected_pts == 0.0:
            assert f is None or f.points == 0.0
        else:
            assert f is not None
            assert f.points == expected_pts, f"Failed for amount {amt}"

def test_prior_defaults_scoring():
    inv0 = invoice(prior_defaults=0)
    assert not any(f.label == "Prior defaults" for f in evaluate(inv0).risk.factors)

    inv1 = invoice(prior_defaults=1)
    f1 = next(f for f in evaluate(inv1).risk.factors if f.label == "Prior defaults")
    assert f1.points == 15.0
    assert f1.reason_code == "PRIOR_DEFAULT"

    inv2 = invoice(prior_defaults=2)
    f2 = next(f for f in evaluate(inv2).risk.factors if f.label == "Prior defaults")
    assert f2.points == 30.0
    assert f2.reason_code == "MULTIPLE_PRIOR_DEFAULTS"

    inv5 = invoice(prior_defaults=5)
    f5 = next(f for f in evaluate(inv5).risk.factors if f.label == "Prior defaults")
    assert f5.points == 30.0  # capped at +30

def test_invoice_maturity_urgency():
    today = date.today()
    # >60 days -> 0, 31-60 -> +2, 15-30 -> +5, 1-14 -> +8
    test_cases = [
        (65, 0.0, None),
        (60, 2.0, "MATURITY_MEDIUM_TENOR"),
        (31, 2.0, "MATURITY_MEDIUM_TENOR"),
        (30, 5.0, "MATURITY_SHORT_TENOR"),
        (15, 5.0, "MATURITY_SHORT_TENOR"),
        (14, 8.0, "MATURITY_NEAR_DUE"),
        (1, 8.0, "MATURITY_NEAR_DUE"),
    ]
    for days, expected_pts, expected_code in test_cases:
        inv = invoice(issue_date=today - timedelta(days=2), due_date=today + timedelta(days=days))
        eval_res = evaluate(inv)
        f = next((f for f in eval_res.risk.factors if f.label == "Invoice maturity"), None)
        if expected_pts == 0.0:
            assert f is None
        else:
            assert f is not None
            assert f.points == expected_pts, f"Failed for {days} days"
            assert f.reason_code == expected_code

def test_verification_valid_invoice():
    result = verify_invoice(invoice())
    assert result.status == VerificationStatus.VERIFIED
    assert result.confidence == 0.95
    assert "GSTIN_VERIFIED" in result.reason_codes
    assert "PO_VERIFIED" in result.reason_codes
    assert "invoice_number" in result.verified_fields
    assert "supplier_name" in result.verified_fields
    assert "buyer_name" in result.verified_fields
    assert "amount" in result.verified_fields

def test_verification_invalid_gstin_formats():
    # length != 15
    assert verify_invoice(invoice(gstin="INVALID")).status == VerificationStatus.REJECTED
    # invalid state code (e.g. 00 or 99 is ok, 45 is invalid)
    assert verify_invoice(invoice(gstin="45ABCDE1234F1Z5")).status == VerificationStatus.REJECTED
    # fake repetitive
    assert verify_invoice(invoice(gstin="AAAAAAAAAAAAAAA")).status == VerificationStatus.REJECTED
    assert verify_invoice(invoice(gstin="000000000000000")).status == VerificationStatus.REJECTED

def test_verification_missing_po_and_gstin_uncertainty():
    inv = invoice(gstin=None, purchase_order_reference=None)
    res = verify_invoice(inv)
    assert res.status == VerificationStatus.PARTIALLY_VERIFIED
    assert "GSTIN_MISSING" in res.reason_codes
    assert "PO_MISSING" in res.reason_codes
    assert set(res.uncertain_fields) == {"gstin", "purchase_order_reference"}

def test_verification_date_checks():
    today = date.today()
    # Past due
    past_inv = invoice(due_date=today - timedelta(days=1))
    past_res = verify_invoice(past_inv)
    assert past_res.status == VerificationStatus.REJECTED
    assert "INVOICE_PAST_DUE" in past_res.reason_codes

    # Future issue date
    future_inv = invoice(issue_date=today + timedelta(days=2), due_date=today + timedelta(days=20))
    future_res = verify_invoice(future_inv)
    assert future_res.status == VerificationStatus.REJECTED
    assert "INVOICE_ISSUED_IN_FUTURE" in future_res.reason_codes

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
    assert len(entry.risk.factors) > 0
    for f in entry.risk.factors:
        assert f.label
        assert f.impact in ["positive", "negative", "neutral"]
        assert isinstance(f.points, (int, float))
        assert len(f.explanation) > 0
        assert f.reason_code is not None

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

