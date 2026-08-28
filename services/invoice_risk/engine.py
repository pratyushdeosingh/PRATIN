"""Transparent demo verification and risk policy."""
from datetime import date

from contracts.models import (
    Invoice,
    InvoiceEvaluation,
    RiskAssessment,
    RiskBand,
    RiskFactor,
    VerificationResult,
    VerificationStatus,
)


def verify_invoice(invoice: Invoice) -> VerificationResult:
    reasons: list[str] = []
    verified = ["invoice_number", "supplier_name", "buyer_name", "amount", "issue_date", "due_date"]
    uncertain: list[str] = []
    if invoice.due_date <= date.today():
        return VerificationResult(status=VerificationStatus.REJECTED, confidence=0.96, verified_fields=verified,
            uncertain_fields=[], reasons=["Invoice is already past its due date."])
    if not invoice.gstin:
        uncertain.append("gstin")
        reasons.append("Supplier GSTIN was not supplied for the simulated consistency check.")
    elif len("".join(ch for ch in invoice.gstin if ch.isalnum())) != 15:
        return VerificationResult(status=VerificationStatus.REJECTED, confidence=0.94, verified_fields=verified,
            uncertain_fields=["gstin"], reasons=["GSTIN format is inconsistent with the 15-character demo rule."])
    else:
        verified.append("gstin")
    if not invoice.purchase_order_reference:
        uncertain.append("purchase_order_reference")
        reasons.append("Purchase-order linkage is missing.")
    else:
        verified.append("purchase_order_reference")
    status = VerificationStatus.VERIFIED if not uncertain else VerificationStatus.PARTIALLY_VERIFIED
    reasons.insert(0, "Invoice fields are internally consistent under the synthetic verification policy.")
    return VerificationResult(status=status, confidence=0.95 if not uncertain else 0.78,
        verified_fields=verified, uncertain_fields=uncertain, reasons=reasons)


def assess_risk(invoice: Invoice, verification: VerificationResult) -> RiskAssessment:
    factors: list[RiskFactor] = []
    score = 38.0
    def factor(label: str, points: float, explanation: str):
        nonlocal score
        score += points
        factors.append(RiskFactor(label=label, points=points,
            impact="negative" if points > 0 else "positive" if points < 0 else "neutral", explanation=explanation))
    factor("Buyer reliability", -18 * invoice.buyer_rating, f"Buyer reliability signal is {invoice.buyer_rating:.0%}.")
    factor("Payment history", -12 if invoice.on_time_payment_ratio >= .85 else 10,
           f"Supplier on-time payment ratio is {invoice.on_time_payment_ratio:.0%}.")
    factor("Supplier operating history", -7 if invoice.supplier_history_months >= 24 else 8,
           f"{invoice.supplier_history_months} months of supplier history are available.")
    if invoice.prior_defaults:
        factor("Prior defaults", min(30, 15 * invoice.prior_defaults), f"{invoice.prior_defaults} prior default(s) reported.")
    if verification.status == VerificationStatus.PARTIALLY_VERIFIED:
        factor("Verification uncertainty", 12, "Missing fields increase information asymmetry.")
    elif verification.status == VerificationStatus.REJECTED:
        factor("Verification rejected", 45, "Invoice failed the synthetic verification policy.")
    if invoice.amount >= 5_000_000:
        factor("Large ticket", 8, "Large invoice size increases concentration risk in the demo policy.")
    score = round(max(0, min(100, score)), 1)
    band = RiskBand.LOW if score < 30 else RiskBand.MODERATE if score < 55 else RiskBand.HIGH if score < 75 else RiskBand.SEVERE
    return RiskAssessment(score=score, band=band, confidence=round(.96 - .08 * len(verification.uncertain_fields), 2),
        factors=factors, missing_information=verification.uncertain_fields)


def evaluate(invoice: Invoice) -> InvoiceEvaluation:
    verification = verify_invoice(invoice)
    return InvoiceEvaluation(verification=verification, risk=assess_risk(invoice, verification))

