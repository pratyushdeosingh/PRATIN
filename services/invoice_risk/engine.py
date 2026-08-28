"""Transparent demo verification and risk policy."""
from datetime import date
from uuid import uuid4

from contracts.models import (
    Invoice,
    InvoiceEvaluation,
    RiskAssessment,
    RiskBand,
    RiskFactor,
    RiskLedgerEntry,
    VerificationResult,
    VerificationStatus,
    utc_now,
)


def verify_invoice(invoice: Invoice) -> VerificationResult:
    reasons: list[str] = []
    reason_codes: list[str] = []
    verified: list[str] = []
    uncertain: list[str] = []
    today = date.today()

    # 1. Invoice Number
    if not invoice.invoice_number or not invoice.invoice_number.strip():
        return VerificationResult(
            status=VerificationStatus.REJECTED,
            confidence=0.96,
            verified_fields=verified,
            uncertain_fields=uncertain,
            reasons=["Invoice number is required and cannot be empty."],
            reason_codes=["INVOICE_NUMBER_MISSING"],
        )
    verified.append("invoice_number")

    # 2. Supplier
    if not invoice.supplier_name or not invoice.supplier_name.strip():
        return VerificationResult(
            status=VerificationStatus.REJECTED,
            confidence=0.96,
            verified_fields=verified,
            uncertain_fields=uncertain,
            reasons=["Supplier name is missing."],
            reason_codes=["SUPPLIER_MISSING"],
        )
    verified.append("supplier_name")

    # 3. Buyer
    if not invoice.buyer_name or not invoice.buyer_name.strip():
        return VerificationResult(
            status=VerificationStatus.REJECTED,
            confidence=0.96,
            verified_fields=verified,
            uncertain_fields=uncertain,
            reasons=["Buyer name is missing."],
            reason_codes=["BUYER_MISSING"],
        )
    verified.append("buyer_name")

    # 4. Amount
    if invoice.amount <= 0:
        return VerificationResult(
            status=VerificationStatus.REJECTED,
            confidence=0.96,
            verified_fields=verified,
            uncertain_fields=uncertain,
            reasons=["Invoice amount must be greater than zero."],
            reason_codes=["INVOICE_AMOUNT_INVALID"],
        )
    verified.append("amount")

    # 5. Date consistency
    if invoice.issue_date > today:
        return VerificationResult(
            status=VerificationStatus.REJECTED,
            confidence=0.96,
            verified_fields=verified,
            uncertain_fields=uncertain,
            reasons=["Invoice issue date cannot be in the future."],
            reason_codes=["INVOICE_ISSUED_IN_FUTURE"],
        )
    verified.append("issue_date")

    if invoice.due_date <= invoice.issue_date:
        return VerificationResult(
            status=VerificationStatus.REJECTED,
            confidence=0.96,
            verified_fields=verified,
            uncertain_fields=uncertain,
            reasons=["Due date must be after issue date."],
            reason_codes=["DATE_INCONSISTENT"],
        )

    if invoice.due_date <= today:
        return VerificationResult(
            status=VerificationStatus.REJECTED,
            confidence=0.96,
            verified_fields=verified,
            uncertain_fields=uncertain,
            reasons=["Invoice is already past its due date."],
            reason_codes=["INVOICE_PAST_DUE"],
        )
    verified.append("due_date")

    # 6. GSTIN validation
    if not invoice.gstin or not invoice.gstin.strip():
        uncertain.append("gstin")
        reasons.append("Supplier GSTIN was not supplied for the simulated consistency check.")
        reason_codes.append("GSTIN_MISSING")
    else:
        norm = "".join(ch for ch in invoice.gstin if ch.isalnum()).upper()
        if len(norm) != 15:
            return VerificationResult(
                status=VerificationStatus.REJECTED,
                confidence=0.94,
                verified_fields=verified,
                uncertain_fields=["gstin"],
                reasons=["GSTIN format is inconsistent with the 15-character demo rule."],
                reason_codes=["GSTIN_INVALID"],
            )
        state_prefix = norm[:2]
        is_valid_state = state_prefix.isdigit() and (1 <= int(state_prefix) <= 38 or int(state_prefix) in (97, 99))
        is_fake_repetitive = len(set(norm)) <= 3 or norm.startswith("AAAA") or norm == "000000000000000" or norm == "111111111111111"
        if not is_valid_state or is_fake_repetitive:
            return VerificationResult(
                status=VerificationStatus.REJECTED,
                confidence=0.94,
                verified_fields=verified,
                uncertain_fields=["gstin"],
                reasons=["GSTIN state code or character distribution is invalid for the demo rule."],
                reason_codes=["GSTIN_INVALID"],
            )
        verified.append("gstin")
        reason_codes.append("GSTIN_VERIFIED")

    # 7. Purchase Order Reference
    if not invoice.purchase_order_reference or not invoice.purchase_order_reference.strip():
        uncertain.append("purchase_order_reference")
        reasons.append("Purchase-order linkage is missing.")
        reason_codes.append("PO_MISSING")
    else:
        verified.append("purchase_order_reference")
        reason_codes.append("PO_VERIFIED")

    status = VerificationStatus.VERIFIED if not uncertain else VerificationStatus.PARTIALLY_VERIFIED
    reasons.insert(0, "Invoice fields are internally consistent under the synthetic verification policy." if not uncertain else "Invoice is partially verified with explicit information uncertainty.")
    confidence = 0.95 if not uncertain else round(0.95 - 0.08 * len(uncertain), 2)
    return VerificationResult(
        status=status,
        confidence=confidence,
        verified_fields=verified,
        uncertain_fields=uncertain,
        reasons=reasons,
        reason_codes=reason_codes,
    )


def assess_risk(invoice: Invoice, verification: VerificationResult) -> RiskAssessment:
    factors: list[RiskFactor] = []
    score = 38.0

    def factor(label: str, points: float, explanation: str, reason_code: str):
        nonlocal score
        score += points
        impact = "negative" if points > 0 else "positive" if points < 0 else "neutral"
        factors.append(RiskFactor(
            label=label,
            points=round(points, 1),
            impact=impact,
            explanation=explanation,
            reason_code=reason_code,
        ))

    # 1. Buyer reliability (continuous)
    buyer_pts = -18.0 * invoice.buyer_rating
    buyer_code = "BUYER_RELIABILITY_STRONG" if invoice.buyer_rating >= 0.75 else "BUYER_RELIABILITY_WEAK"
    factor(
        "Buyer reliability",
        buyer_pts,
        f"Buyer reliability signal is {invoice.buyer_rating:.0%}.",
        buyer_code,
    )

    # 2. Payment history (graduated)
    # >=95% -> -15, 90-94.99% -> -10, 85-89.99% -> -5, 70-84.99% -> +5, 50-69.99% -> +12, <50% -> +20
    r = invoice.on_time_payment_ratio
    if r >= 0.95:
        factor("Payment history", -15.0, f"Exceptional on-time payment ratio of {r:.0%}.", "PAYMENT_HISTORY_STRONG")
    elif r >= 0.90:
        factor("Payment history", -10.0, f"Strong on-time payment ratio of {r:.0%}.", "PAYMENT_HISTORY_STRONG")
    elif r >= 0.85:
        factor("Payment history", -5.0, f"Acceptable on-time payment ratio of {r:.0%}.", "PAYMENT_HISTORY_STRONG")
    elif r >= 0.70:
        factor("Payment history", 5.0, f"On-time payment ratio of {r:.0%} shows moderate payment delays.", "PAYMENT_HISTORY_WEAK")
    elif r >= 0.50:
        factor("Payment history", 12.0, f"On-time payment ratio of {r:.0%} increases payment risk.", "PAYMENT_HISTORY_WEAK")
    else:
        factor("Payment history", 20.0, f"On-time payment ratio of {r:.0%} reflects critical delinquency.", "PAYMENT_HISTORY_CRITICAL")

    # 3. Supplier operating history (graduated)
    # <6 -> +12, 6-11 -> +8, 12-23 -> +3, 24-35 -> -5, >=36 -> -8
    m = invoice.supplier_history_months
    if m < 6:
        factor("Supplier operating history", 12.0, f"New supplier with only {m} months of operating history.", "SUPPLIER_MATURITY_NEW")
    elif m < 12:
        factor("Supplier operating history", 8.0, f"Limited supplier history of {m} months.", "SUPPLIER_MATURITY_WEAK")
    elif m < 24:
        factor("Supplier operating history", 3.0, f"Developing supplier relationship with {m} months of history.", "SUPPLIER_MATURITY_WEAK")
    elif m < 36:
        factor("Supplier operating history", -5.0, f"Established supplier operating history of {m} months.", "SUPPLIER_MATURITY_STRONG")
    else:
        factor("Supplier operating history", -8.0, f"Mature supplier relationship with {m} months of history.", "SUPPLIER_MATURITY_STRONG")

    # 4. Prior defaults
    if invoice.prior_defaults > 0:
        d = invoice.prior_defaults
        pts = min(30.0, 15.0 * d)
        code = "PRIOR_DEFAULT" if d == 1 else "MULTIPLE_PRIOR_DEFAULTS"
        factor("Prior defaults", pts, f"{d} prior default(s) reported.", code)

    # 5. Invoice amount / concentration risk (graduated)
    # <₹10L -> 0, ₹10-24.99L -> +2, ₹25-49.99L -> +4, ₹50-99.99L -> +8, >=₹1Cr -> +12
    amt = invoice.amount
    if amt >= 10_000_000:
        factor("Large ticket", 12.0, f"Very large invoice size of ₹{amt:,.0f} creates high concentration risk.", "VERY_LARGE_INVOICE")
    elif amt >= 5_000_000:
        factor("Large ticket", 8.0, f"Large invoice size of ₹{amt:,.0f} increases concentration risk in the demo policy.", "LARGE_INVOICE")
    elif amt >= 2_500_000:
        factor("Large ticket", 4.0, f"Invoice amount of ₹{amt:,.0f} presents moderate concentration risk.", "LARGE_INVOICE")
    elif amt >= 1_000_000:
        factor("Large ticket", 2.0, f"Invoice amount of ₹{amt:,.0f} presents low concentration risk.", "CONCENTRATION_RISK")

    # 6. Invoice maturity / urgency
    # >60 days -> 0, 31-60 -> +2, 15-30 -> +5, 1-14 -> +8
    today = date.today()
    if verification.status != VerificationStatus.REJECTED and invoice.due_date > today:
        days_until_due = (invoice.due_date - today).days
        if days_until_due <= 14:
            factor("Invoice maturity", 8.0, f"Invoice is due in {days_until_due} days, increasing repayment-urgency risk.", "MATURITY_NEAR_DUE")
        elif days_until_due <= 30:
            factor("Invoice maturity", 5.0, f"Invoice is due in {days_until_due} days, short tenor window.", "MATURITY_SHORT_TENOR")
        elif days_until_due <= 60:
            factor("Invoice maturity", 2.0, f"Invoice is due in {days_until_due} days, moderate tenor window.", "MATURITY_MEDIUM_TENOR")

    # 7. Verification uncertainty / rejection
    if verification.status == VerificationStatus.PARTIALLY_VERIFIED:
        factor("Verification uncertainty", 12.0, "Missing fields increase information asymmetry.", "VERIFICATION_UNCERTAIN")
    elif verification.status == VerificationStatus.REJECTED:
        factor("Verification rejected", 45.0, "Invoice failed the synthetic verification policy.", "VERIFICATION_REJECTED")

    score = round(max(0.0, min(100.0, score)), 1)
    band = RiskBand.LOW if score < 30 else RiskBand.MODERATE if score < 55 else RiskBand.HIGH if score < 75 else RiskBand.SEVERE
    confidence = round(0.96 - 0.08 * len(verification.uncertain_fields), 2)
    return RiskAssessment(
        score=score,
        band=band,
        confidence=confidence,
        factors=factors,
        missing_information=verification.uncertain_fields,
    )


def evaluate(invoice: Invoice) -> InvoiceEvaluation:
    verification = verify_invoice(invoice)
    return InvoiceEvaluation(verification=verification, risk=assess_risk(invoice, verification))


def create_risk_ledger_entry(
    invoice: Invoice,
    opportunity_id: str | None = None,
    evaluation: InvoiceEvaluation | None = None,
    entry_id: str | None = None,
) -> RiskLedgerEntry:
    if evaluation is None:
        evaluation = evaluate(invoice)
    return RiskLedgerEntry(
        id=entry_id or ("RSK-" + uuid4().hex[:10].upper()),
        opportunity_id=opportunity_id,
        invoice_number=invoice.invoice_number,
        supplier_name=invoice.supplier_name,
        buyer_name=invoice.buyer_name,
        amount=invoice.amount,
        evaluated_at=utc_now(),
        verification=evaluation.verification,
        risk=evaluation.risk,
        provenance=evaluation.provenance,
    )

