from datetime import date, timedelta
from contracts.models import Invoice, VerificationStatus
from services.invoice_risk.engine import evaluate, verify_invoice

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

