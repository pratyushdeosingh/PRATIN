"""Deterministic tests for Duplicate Invoice Detection and Invoice Consistency Checks."""
from datetime import date, timedelta
import pytest
from contracts.models import (
    Invoice,
    VerificationStatus,
    RiskBand,
)
from services.invoice_risk.engine import (
    check_duplicate_invoice,
    evaluate,
    verify_invoice,
)
from services.invoice_risk.pdf_parser import parse_and_evaluate_pdf
import fitz


def create_base_invoice(
    invoice_number: str = "INV-2026-100",
    supplier_name: str = "Apex Precision Ltd",
    buyer_name: str = "Zenith Motors",
    amount: float = 1_000_000.0,
    subtotal: float | None = None,
    tax_amount: float | None = None,
    issue_date: date | None = None,
    due_date: date | None = None,
) -> Invoice:
    today = date.today()
    return Invoice(
        invoice_number=invoice_number,
        supplier_name=supplier_name,
        buyer_name=buyer_name,
        amount=amount,
        currency="INR",
        issue_date=issue_date or (today - timedelta(days=5)),
        due_date=due_date or (today + timedelta(days=45)),
        industry="Manufacturing",
        gstin="27ABCDE1234F1Z5",
        purchase_order_reference="PO-2026-99",
        subtotal=subtotal,
        tax_amount=tax_amount,
        buyer_rating=0.85,
        supplier_history_months=30,
        on_time_payment_ratio=0.92,
        prior_defaults=0,
    )


def make_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((40, 60), text, fontsize=10)
    buf = doc.tobytes()
    doc.close()
    return buf


# =========================================================================
# FEATURE 1: DUPLICATE INVOICE TESTS
# =========================================================================

def test_first_submission_is_not_duplicate():
    inv = create_base_invoice()
    res = check_duplicate_invoice(inv, existing_invoices=[])
    assert res.duplicate_detected is False
    assert res.matched_invoice_number is None

    eval_res = evaluate(inv, existing_invoices=[])
    assert eval_res.verification.duplicate_check is not None
    assert eval_res.verification.duplicate_check.duplicate_detected is False
    assert "DUPLICATE_INVOICE" not in eval_res.verification.reason_codes
    assert not any(f.label == "Duplicate invoice" for f in eval_res.risk.factors)


def test_exact_duplicate_invoice_detection():
    inv1 = create_base_invoice(invoice_number="INV-DUP-01", supplier_name="Tata Steel", buyer_name="Mahindra", amount=500000.0)
    inv2 = create_base_invoice(invoice_number="INV-DUP-01", supplier_name="Tata Steel", buyer_name="Mahindra", amount=500000.0)

    res = check_duplicate_invoice(inv2, existing_invoices=[inv1])
    assert res.duplicate_detected is True
    assert res.matched_invoice_number == "INV-DUP-01"
    assert "Same invoice number" in res.reasons

    eval_res = evaluate(inv2, existing_invoices=[inv1])
    assert eval_res.verification.duplicate_check.duplicate_detected is True
    assert "DUPLICATE_INVOICE" in eval_res.verification.reason_codes
    dup_factor = next((f for f in eval_res.risk.factors if f.label == "Duplicate invoice"), None)
    assert dup_factor is not None
    assert dup_factor.points == 35.0
    assert dup_factor.reason_code == "DUPLICATE_INVOICE"


def test_different_supplier_same_invoice_number_not_duplicate():
    inv1 = create_base_invoice(invoice_number="INV-COMMON-100", supplier_name="Supplier Alpha")
    inv2 = create_base_invoice(invoice_number="INV-COMMON-100", supplier_name="Supplier Beta")

    res = check_duplicate_invoice(inv2, existing_invoices=[inv1])
    assert res.duplicate_detected is False


def test_different_buyer_same_invoice_number_not_duplicate():
    inv1 = create_base_invoice(invoice_number="INV-COMMON-100", buyer_name="Buyer Alpha")
    inv2 = create_base_invoice(invoice_number="INV-COMMON-100", buyer_name="Buyer Beta")

    res = check_duplicate_invoice(inv2, existing_invoices=[inv1])
    assert res.duplicate_detected is False


def test_different_amount_same_invoice_number_not_duplicate():
    inv1 = create_base_invoice(invoice_number="INV-AMT-100", amount=500_000.0)
    inv2 = create_base_invoice(invoice_number="INV-AMT-100", amount=600_000.0)

    res = check_duplicate_invoice(inv2, existing_invoices=[inv1])
    assert res.duplicate_detected is False


def test_different_invoice_number_same_parties_not_duplicate():
    inv1 = create_base_invoice(invoice_number="INV-001", supplier_name="Supplier Alpha", buyer_name="Buyer X", amount=100000.0)
    inv2 = create_base_invoice(invoice_number="INV-002", supplier_name="Supplier Alpha", buyer_name="Buyer X", amount=100000.0)

    res = check_duplicate_invoice(inv2, existing_invoices=[inv1])
    assert res.duplicate_detected is False


def test_case_and_whitespace_normalization_in_duplicate_check():
    inv1 = create_base_invoice(
        invoice_number="inv-2026-99 ",
        supplier_name="  Bharat Forge   Limited ",
        buyer_name="maruti suzuki ",
        amount=1200000.00,
    )
    inv2 = create_base_invoice(
        invoice_number="INV-2026-99",
        supplier_name="bharat forge limited",
        buyer_name="MARUTI SUZUKI",
        amount=1200000.00,
    )
    res = check_duplicate_invoice(inv2, existing_invoices=[inv1])
    assert res.duplicate_detected is True


def test_multiple_invoices_isolated_check():
    inv1 = create_base_invoice(invoice_number="INV-A", supplier_name="Sup A", amount=100000.0)
    inv2 = create_base_invoice(invoice_number="INV-B", supplier_name="Sup B", amount=200000.0)
    inv3 = create_base_invoice(invoice_number="INV-C", supplier_name="Sup C", amount=300000.0)

    new_inv = create_base_invoice(invoice_number="INV-B", supplier_name="Sup B", amount=200000.0)
    res = check_duplicate_invoice(new_inv, existing_invoices=[inv1, inv2, inv3])
    assert res.duplicate_detected is True
    assert res.matched_invoice_number == "INV-B"


# =========================================================================
# FEATURE 2: INVOICE CONSISTENCY TESTS
# =========================================================================

def test_amount_consistency_valid():
    inv = create_base_invoice(
        amount=1_180_000.0,
        subtotal=1_000_000.0,
        tax_amount=180_000.0,
    )
    verif = verify_invoice(inv)
    assert verif.status == VerificationStatus.VERIFIED
    assert "amount_consistency" in verif.verified_fields
    assert "AMOUNT_CONSISTENT" in verif.reason_codes
    assert "AMOUNT_MISMATCH" not in verif.reason_codes


def test_amount_consistency_mismatch():
    inv = create_base_invoice(
        amount=1_250_000.0,  # Declared 12.5L
        subtotal=1_000_000.0,
        tax_amount=180_000.0,  # Subtotal + Tax = 11.8L (Difference 70k)
    )
    verif = verify_invoice(inv)
    assert "amount_consistency" in verif.uncertain_fields
    assert "AMOUNT_MISMATCH" in verif.reason_codes
    assert len(verif.consistency_warnings) > 0

    eval_res = evaluate(inv)
    mismatch_factor = next((f for f in eval_res.risk.factors if f.label == "Amount consistency mismatch"), None)
    assert mismatch_factor is not None
    assert mismatch_factor.points == 20.0
    assert mismatch_factor.reason_code == "AMOUNT_MISMATCH"


def test_missing_subtotal_tax_retains_uncertainty_not_fabricated():
    inv = create_base_invoice(
        amount=1_000_000.0,
        subtotal=None,
        tax_amount=None,
    )
    verif = verify_invoice(inv)
    # Should not produce AMOUNT_MISMATCH
    assert "AMOUNT_MISMATCH" not in verif.reason_codes
    eval_res = evaluate(inv)
    assert not any(f.label == "Amount consistency mismatch" for f in eval_res.risk.factors)


def test_non_positive_amount_rejected():
    with pytest.raises(Exception):
        create_base_invoice(amount=0)

    with pytest.raises(Exception):
        create_base_invoice(amount=-500)


def test_date_consistency_due_before_issue():
    today = date.today()
    with pytest.raises(Exception):
        create_base_invoice(
            issue_date=today,
            due_date=today - timedelta(days=5),
        )


# =========================================================================
# REGRESSION TESTS: MISSING DUE DATE & MATURITY HANDLING
# =========================================================================

def test_pdf_without_due_date_does_not_invent_maturity():
    pdf_text = """
    TAX INVOICE
    Supplier Name: Bharat Forge
    Buyer Name: Mahindra Auto
    Invoice Number: INV-NO-DUEDATE-01
    Invoice Date: 2026-08-15
    Total Amount: INR 850,000.00
    GSTIN: 27ABCDE1234F1Z5
    """
    pdf_bytes = make_pdf(pdf_text)
    res = parse_and_evaluate_pdf(pdf_bytes, filename="no_duedate.pdf")
    assert res.status == "SUCCESS"
    assert res.invoice is not None
    assert res.invoice.due_date is None
    assert res.extracted_fields.due_date is None
    assert "due_date" in res.extracted_fields.missing_fields

    verif = res.evaluation.verification
    assert verif.status == VerificationStatus.PARTIALLY_VERIFIED
    assert "due_date" in verif.uncertain_fields
    assert "DUE_DATE_MISSING" in verif.reason_codes

    maturity_factor = next((f for f in res.evaluation.risk.factors if f.label == "Invoice maturity"), None)
    assert maturity_factor is not None
    assert maturity_factor.points == 0.0
    assert maturity_factor.reason_code == "MATURITY_UNKNOWN"
    assert "Due date unavailable" in maturity_factor.explanation
    assert "52 days" not in maturity_factor.explanation
    assert "days" not in maturity_factor.explanation.lower() or "due date unavailable" in maturity_factor.explanation.lower()


def test_pdf_with_amount_consistency_and_duplicate_flow():
    pdf_text = """
    COMMERCIAL TAX INVOICE
    Supplier Name: Kirloskar Pumps
    Buyer Name: Larsen and Toubro
    Invoice Number: INV-KIR-7701
    Invoice Date: 2026-08-15
    Due Date: 2026-10-15
    GSTIN: 27ABCDE1234F1Z5
    Purchase Order: PO-LNT-881

    Subtotal: INR 1,000,000.00
    IGST: INR 180,000.00
    Total Amount: INR 1,180,000.00
    """
    pdf_bytes = make_pdf(pdf_text)

    # 1. First parse: verified and consistent
    res1 = parse_and_evaluate_pdf(pdf_bytes, filename="kirloskar.pdf", existing_invoices=[])
    assert res1.status == "SUCCESS"
    assert res1.invoice is not None
    assert res1.invoice.subtotal == 1000000.0
    assert res1.invoice.tax_amount == 180000.0
    assert res1.evaluation.verification.status == VerificationStatus.VERIFIED
    assert "AMOUNT_CONSISTENT" in res1.evaluation.verification.reason_codes
    assert res1.evaluation.verification.duplicate_check.duplicate_detected is False

    # 2. Second parse with first invoice in history: flags duplicate
    res2 = parse_and_evaluate_pdf(pdf_bytes, filename="kirloskar_copy.pdf", existing_invoices=[res1.invoice])
    assert res2.status == "SUCCESS"
    assert res2.evaluation.verification.duplicate_check.duplicate_detected is True
    assert "DUPLICATE_INVOICE" in res2.evaluation.verification.reason_codes
    dup_factor = next((f for f in res2.evaluation.risk.factors if f.label == "Duplicate invoice"), None)
    assert dup_factor is not None
    assert dup_factor.points == 35.0


def test_two_pdfs_with_different_and_missing_due_dates():
    today = date.today()
    due1 = (today + timedelta(days=20)).strftime("%Y-%m-%d")
    pdf1_text = f"""
    TAX INVOICE
    Supplier Name: Alpha Ltd
    Buyer Name: Beta Corp
    Invoice Number: INV-A-1
    Invoice Date: 2026-08-15
    Due Date: {due1}
    Total Amount: INR 500,000.00
    GSTIN: 27ABCDE1234F1Z5
    """
    pdf2_text = """
    TAX INVOICE
    Supplier Name: Gamma Ltd
    Buyer Name: Delta Corp
    Invoice Number: INV-G-2
    Invoice Date: 2026-08-15
    Total Amount: INR 600,000.00
    GSTIN: 27ABCDE1234F1Z5
    """
    res1 = parse_and_evaluate_pdf(make_pdf(pdf1_text), filename="pdf1.pdf")
    res2 = parse_and_evaluate_pdf(make_pdf(pdf2_text), filename="pdf2.pdf")

    f1 = next(f for f in res1.evaluation.risk.factors if f.label == "Invoice maturity")
    f2 = next(f for f in res2.evaluation.risk.factors if f.label == "Invoice maturity")

    assert f1.reason_code in ("MATURITY_SHORT_TENOR", "MATURITY_NEAR_DUE", "MATURITY_MEDIUM_TENOR")
    assert "days" in f1.explanation
    assert f2.reason_code == "MATURITY_UNKNOWN"
    assert "Due date unavailable" in f2.explanation
