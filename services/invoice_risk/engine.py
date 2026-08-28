"""Transparent demo verification and risk policy."""
from datetime import date
from uuid import uuid4

from contracts.models import (
    CounterpartyHistoricalProfile,
    DuplicateCheckResult,
    GSTINCheckResult,
    Invoice,
    InvoiceEvaluation,
    RiskAssessment,
    RiskBand,
    RiskDecisionSummary,
    RiskFactor,
    RiskFactorSource,
    RiskLedgerEntry,
    RiskSimulationRequest,
    RiskSimulationResult,
    VerificationResult,
    VerificationStatus,
    utc_now,
)


GSTIN_STATE_CODES: dict[str, str] = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
    "97": "Other Territory",
    "99": "Centre Jurisdiction",
}

PAN_ENTITY_TYPES: dict[str, str] = {
    "C": "Company",
    "P": "Individual / Proprietorship",
    "F": "Partnership Firm / LLP",
    "H": "Hindu Undivided Family (HUF)",
    "A": "Association of Persons (AOP)",
    "T": "Trust",
    "B": "Body of Individuals (BOI)",
    "G": "Government Agency",
    "J": "Artificial Juridical Person",
    "L": "Local Authority",
}


def check_gstin_entity_consistency(supplier_name: str, pan_entity_char: str) -> tuple[bool | None, str | None, str | None]:
    """
    Deterministically check whether a supplier name containing corporate/legal suffixes
    matches the PAN entity type encoded in position 4 of PAN (pos 5 of 15-char GSTIN).
    Returns: (entity_match: bool | None, inferred_type: str | None, explanation: str | None)
    """
    s_lower = f" {supplier_name.lower().strip()} "

    is_company = any(
        term in s_lower
        for term in [" private limited ", " pvt ltd ", " pvt. ltd. ", " pvt.ltd. ", " limited ", " ltd. ", " ltd "]
    )
    is_llp = any(
        term in s_lower
        for term in [" llp ", " limited liability partnership ", " partnership ", " & partners ", " and partners "]
    )

    if is_company and not is_llp:
        inferred = "Company"
        if pan_entity_char == "C":
            return True, inferred, None
        elif pan_entity_char == "P":
            return (
                False,
                inferred,
                "Supplier name indicates a Company (Pvt Ltd/Ltd) but GSTIN PAN structure indicates an Individual / Proprietorship ('P').",
            )
        elif pan_entity_char in ("F", "H", "T"):
            pan_desc = PAN_ENTITY_TYPES.get(pan_entity_char, pan_entity_char)
            return (
                False,
                inferred,
                f"Supplier name indicates a Company but GSTIN PAN structure indicates {pan_desc} ('{pan_entity_char}').",
            )
        else:
            return True, inferred, None

    if is_llp:
        inferred = "Partnership Firm / LLP"
        if pan_entity_char == "F":
            return True, inferred, None
        elif pan_entity_char in ("C", "P"):
            pan_desc = PAN_ENTITY_TYPES.get(pan_entity_char, pan_entity_char)
            return (
                False,
                inferred,
                f"Supplier name indicates an LLP / Partnership but GSTIN PAN structure indicates {pan_desc} ('{pan_entity_char}').",
            )
        else:
            return True, inferred, None

    # Generic name -> uncertainty/no false positive
    return None, None, None


RISK_POLICY_WEIGHTS = {
    "BASE_SCORE": 38.0,
    "BUYER_RATING_MULTIPLIER": -18.0,
    "MATURITY_NEAR_DUE": 8.0,
    "MATURITY_SHORT_TENOR": 5.0,
    "MATURITY_MEDIUM_TENOR": 2.0,
    "VERIFICATION_UNCERTAIN": 12.0,
    "VERIFICATION_REJECTED": 45.0,
    "DUPLICATE_INVOICE": 35.0,
    "AMOUNT_MISMATCH": 20.0,
    "GSTIN_ENTITY_MISMATCH": 15.0,
    "GSTIN_STATE_MISMATCH": 10.0,
}


def check_duplicate_invoice(invoice: Invoice, existing_invoices: list[Invoice] | None = None) -> DuplicateCheckResult:
    """Deterministic duplicate invoice detection based on normalized invoice attributes."""
    if not existing_invoices:
        return DuplicateCheckResult()

    norm_inv_no = invoice.invoice_number.strip().upper()
    norm_sup = " ".join(invoice.supplier_name.strip().lower().split())
    norm_buy = " ".join(invoice.buyer_name.strip().lower().split())
    norm_amt = round(invoice.amount, 2)
    norm_curr = invoice.currency.strip().upper()

    for prior in existing_invoices:
        p_inv_no = prior.invoice_number.strip().upper()
        p_sup = " ".join(prior.supplier_name.strip().lower().split())
        p_buy = " ".join(prior.buyer_name.strip().lower().split())
        p_amt = round(prior.amount, 2)
        p_curr = prior.currency.strip().upper()

        # Match when core composite identity is identical
        if (
            norm_inv_no == p_inv_no
            and norm_sup == p_sup
            and norm_buy == p_buy
            and norm_amt == p_amt
            and norm_curr == p_curr
        ):
            return DuplicateCheckResult(
                duplicate_detected=True,
                matched_invoice_number=prior.invoice_number,
                matched_fields=["invoice_number", "supplier_name", "buyer_name", "amount", "currency"],
                reasons=[
                    "Same invoice number",
                    "Same supplier",
                    "Same buyer",
                    "Same amount",
                    "Same currency",
                ],
            )
    return DuplicateCheckResult()


def verify_invoice(invoice: Invoice, existing_invoices: list[Invoice] | None = None) -> VerificationResult:
    reasons: list[str] = []
    reason_codes: list[str] = []
    verified: list[str] = []
    uncertain: list[str] = []
    consistency_warnings: list[str] = []
    today = date.today()
    dup_res = check_duplicate_invoice(invoice, existing_invoices or [])

    # 1. Invoice Number
    if not invoice.invoice_number or not invoice.invoice_number.strip():
        return VerificationResult(
            status=VerificationStatus.REJECTED,
            confidence=0.96,
            verified_fields=verified,
            uncertain_fields=uncertain,
            reasons=["Invoice number is required and cannot be empty."],
            reason_codes=["MISSING_INVOICE_NUMBER", "INVOICE_NUMBER_MISSING"],
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

    # 4. Positive Amount
    if invoice.amount <= 0:
        code = "ZERO_INVOICE_AMOUNT" if invoice.amount == 0 else "NEGATIVE_INVOICE_AMOUNT"
        return VerificationResult(
            status=VerificationStatus.REJECTED,
            confidence=0.96,
            verified_fields=verified,
            uncertain_fields=uncertain,
            reasons=["Invoice amount must be positive."],
            reason_codes=[code, "NON_POSITIVE_AMOUNT", "INVOICE_AMOUNT_INVALID"],
            duplicate_check=dup_res,
            consistency_warnings=["Invoice amount must be strictly positive."],
        )
    verified.append("amount")

    # 5. Date consistency
    if not invoice.issue_date:
        uncertain.append("issue_date")
        reasons.append("Invoice issue date is missing from document.")
        reason_codes.append("ISSUE_DATE_MISSING")
    elif invoice.issue_date > today:
        return VerificationResult(
            status=VerificationStatus.REJECTED,
            confidence=0.96,
            verified_fields=verified,
            uncertain_fields=uncertain,
            reasons=["Invoice issue date cannot be in the future."],
            reason_codes=["INVOICE_ISSUED_IN_FUTURE"],
            duplicate_check=dup_res,
            consistency_warnings=consistency_warnings,
        )
    else:
        verified.append("issue_date")

    if not invoice.due_date:
        uncertain.append("due_date")
        reasons.append("Invoice due date is missing from document.")
        reason_codes.append("DUE_DATE_MISSING")
    else:
        if invoice.issue_date and invoice.due_date <= invoice.issue_date:
            return VerificationResult(
                status=VerificationStatus.REJECTED,
                confidence=0.96,
                verified_fields=verified,
                uncertain_fields=uncertain,
                reasons=["Due date must be strictly after issue date."],
                reason_codes=["INVALID_DATE_SEQUENCE", "DATE_INCONSISTENT"],
                duplicate_check=dup_res,
                consistency_warnings=consistency_warnings,
            )
        if invoice.due_date <= today:
            return VerificationResult(
                status=VerificationStatus.REJECTED,
                confidence=0.96,
                verified_fields=verified,
                uncertain_fields=uncertain,
                reasons=["Invoice is already past its due date."],
                reason_codes=["INVOICE_PAST_DUE"],
                duplicate_check=dup_res,
                consistency_warnings=consistency_warnings,
            )
        verified.append("due_date")

    # 6. Amount consistency (Subtotal + Tax vs Total)
    if invoice.subtotal is not None and invoice.tax_amount is not None:
        expected_total = round(invoice.subtotal + invoice.tax_amount, 2)
        declared_total = round(invoice.amount, 2)
        diff = round(abs(expected_total - declared_total), 2)
        if diff > 1.0:
            uncertain.append("amount_consistency")
            msg = f"Declared total (₹{declared_total:,.2f}) does not match subtotal (₹{invoice.subtotal:,.2f}) + tax (₹{invoice.tax_amount:,.2f}); difference ₹{diff:,.2f}."
            reasons.append(msg)
            reason_codes.append("AMOUNT_MISMATCH")
            consistency_warnings.append(msg)
        else:
            verified.append("amount_consistency")
            reason_codes.append("AMOUNT_CONSISTENT")

    # 7. GSTIN validation & Consistency
    gstin_res: GSTINCheckResult | None = None
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
                duplicate_check=dup_res,
                consistency_warnings=consistency_warnings,
            )
        state_prefix = norm[:2]
        state_name = GSTIN_STATE_CODES.get(state_prefix)
        is_valid_state = state_name is not None
        is_fake_repetitive = len(set(norm)) <= 3 or norm.startswith("AAAA") or norm == "000000000000000" or norm == "111111111111111"
        if not is_valid_state or is_fake_repetitive:
            return VerificationResult(
                status=VerificationStatus.REJECTED,
                confidence=0.94,
                verified_fields=verified,
                uncertain_fields=["gstin"],
                reasons=["GSTIN state code or character distribution is invalid for the demo rule."],
                reason_codes=["GSTIN_INVALID", "INVALID_GSTIN_STATE_CODE"] if not is_valid_state else ["GSTIN_INVALID"],
                duplicate_check=dup_res,
                consistency_warnings=consistency_warnings,
            )

        # GSTIN structure is valid -> Perform consistency checks
        pan_char = norm[5]
        pan_type = PAN_ENTITY_TYPES.get(pan_char, "Other")
        gstin_warnings: list[str] = []
        state_match: bool | None = None
        entity_match: bool | None = None
        inferred_entity: str | None = None

        # Check 2: Supplier Location vs GSTIN State
        if invoice.supplier_state and invoice.supplier_state.strip():
            sup_st_norm = "".join(ch for ch in invoice.supplier_state.lower() if ch.isalnum())
            gst_st_norm = "".join(ch for ch in state_name.lower() if ch.isalnum())
            if sup_st_norm == gst_st_norm or invoice.supplier_state.strip() == state_prefix:
                state_match = True
                reason_codes.append("GSTIN_STATE_CONSISTENT")
            else:
                state_match = False
                state_msg = f"GSTIN_STATE_MISMATCH: Supplier state '{invoice.supplier_state}' does not match GSTIN state '{state_name}' (State Code {state_prefix})."
                reasons.append(state_msg)
                reason_codes.append("GSTIN_STATE_MISMATCH")
                consistency_warnings.append(state_msg)
                gstin_warnings.append(state_msg)

        # Check 4: Supplier Name vs PAN Entity Type
        entity_match, inferred_entity, entity_msg = check_gstin_entity_consistency(invoice.supplier_name, pan_char)
        if entity_match is True:
            reason_codes.append("GSTIN_ENTITY_CONSISTENT")
        elif entity_match is False and entity_msg:
            reasons.append(f"GSTIN_ENTITY_MISMATCH: {entity_msg}")
            reason_codes.append("GSTIN_ENTITY_MISMATCH")
            consistency_warnings.append(f"GSTIN_ENTITY_MISMATCH: {entity_msg}")
            gstin_warnings.append(entity_msg)

        verified.append("gstin")
        reason_codes.append("GSTIN_VERIFIED")
        gstin_res = GSTINCheckResult(
            is_valid_format=True,
            gstin=norm,
            state_code=state_prefix,
            state_name=state_name,
            supplier_state=invoice.supplier_state,
            state_match=state_match,
            pan_entity_code=pan_char,
            pan_entity_type=pan_type,
            supplier_entity_inferred=inferred_entity,
            entity_match=entity_match,
            warnings=gstin_warnings,
        )

    # 8. Purchase Order Reference
    if not invoice.purchase_order_reference or not invoice.purchase_order_reference.strip():
        uncertain.append("purchase_order_reference")
        reasons.append("Purchase-order linkage is missing.")
        reason_codes.append("PO_MISSING")
    else:
        verified.append("purchase_order_reference")
        reason_codes.append("PO_VERIFIED")

    # 9. Duplicate detection
    dup_res = check_duplicate_invoice(invoice, existing_invoices or [])
    if dup_res.duplicate_detected:
        reasons.append(f"Potential duplicate of invoice {dup_res.matched_invoice_number} detected.")
        reason_codes.append("DUPLICATE_INVOICE")

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
        duplicate_check=dup_res,
        gstin_check=gstin_res,
        consistency_warnings=consistency_warnings,
    )


KNOWN_COUNTERPARTY_PROFILES: dict[str, dict] = {
    # Buyer profiles (historical repayment records)
    "orion auto systems": {"buyer_rating": 0.88, "on_time_payment_ratio": 0.93, "prior_defaults": 0},
    "aster healthcare": {"buyer_rating": 0.94, "on_time_payment_ratio": 0.96, "prior_defaults": 0},
    "zenith automotive ltd": {"buyer_rating": 0.85, "on_time_payment_ratio": 0.92, "prior_defaults": 0},
    "beta motors": {"buyer_rating": 0.80, "on_time_payment_ratio": 0.88, "prior_defaults": 0},
    "urban cart": {"buyer_rating": 0.42, "on_time_payment_ratio": 0.61, "prior_defaults": 1},
    # Supplier profiles (historical supplier operating records)
    "shakti components": {"supplier_history_months": 38},
    "nova pharma pack": {"supplier_history_months": 38},
    "apex precision engineering pvt ltd": {"supplier_history_months": 36},
    "alpha engineering": {"supplier_history_months": 24},
    "rapid retail works": {"supplier_history_months": 9},
}


def resolve_counterparty_profile(
    invoice: Invoice,
    existing_invoices: list[Invoice] | None = None,
) -> CounterpartyHistoricalProfile:
    """
    Resolve historical counterparty metrics deterministically.
    1. If explicit counterparty_profile attached, use it.
    2. If explicit profile fields set on invoice, use them.
    3. If historical invoices exist in store, calculate deterministically from store records.
    4. If matched in known counterparty registry, use registry records.
    5. Otherwise, return UNAVAILABLE with None fields (no fake values).
    """
    if invoice.counterparty_profile is not None:
        return invoice.counterparty_profile

    has_explicit = any(
        v is not None
        for v in (invoice.buyer_rating, invoice.on_time_payment_ratio, invoice.supplier_history_months, invoice.prior_defaults)
    )
    if has_explicit:
        return CounterpartyHistoricalProfile(
            buyer_rating=invoice.buyer_rating,
            on_time_payment_ratio=invoice.on_time_payment_ratio,
            supplier_history_months=invoice.supplier_history_months,
            prior_defaults=invoice.prior_defaults if invoice.prior_defaults is not None else 0,
            source="SEEDED_REGISTRY",
            provenance_detail="Explicit historical profile supplied on invoice input",
        )

    b_norm = invoice.buyer_name.strip().lower()
    s_norm = invoice.supplier_name.strip().lower()
    store_buyer_invoices = [inv for inv in (existing_invoices or []) if inv.buyer_name.strip().lower() == b_norm]
    store_supplier_invoices = [inv for inv in (existing_invoices or []) if inv.supplier_name.strip().lower() == s_norm]

    calc_buyer_rating: float | None = None
    calc_on_time_ratio: float | None = None
    calc_supplier_months: int | None = None
    calc_prior_defaults: int | None = None
    source = "UNAVAILABLE"
    provenance = "No historical counterparty records found"

    if store_buyer_invoices or store_supplier_invoices:
        source = "STORE_DERIVED"
        provenance = f"Calculated from {len(store_buyer_invoices)} buyer and {len(store_supplier_invoices)} supplier historical records in store"
        if store_buyer_invoices:
            ratings = [inv.buyer_rating for inv in store_buyer_invoices if inv.buyer_rating is not None]
            calc_buyer_rating = round(sum(ratings) / len(ratings), 2) if ratings else None
            ratios = [inv.on_time_payment_ratio for inv in store_buyer_invoices if inv.on_time_payment_ratio is not None]
            calc_on_time_ratio = round(sum(ratios) / len(ratios), 2) if ratios else None
            defaults = [inv.prior_defaults for inv in store_buyer_invoices if inv.prior_defaults is not None]
            calc_prior_defaults = max(defaults) if defaults else 0

        if store_supplier_invoices:
            hist_months = [inv.supplier_history_months for inv in store_supplier_invoices if inv.supplier_history_months is not None]
            calc_supplier_months = max(hist_months) if hist_months else None

    if calc_buyer_rating is None and b_norm in KNOWN_COUNTERPARTY_PROFILES:
        b_data = KNOWN_COUNTERPARTY_PROFILES[b_norm]
        calc_buyer_rating = b_data.get("buyer_rating")
        calc_on_time_ratio = b_data.get("on_time_payment_ratio")
        calc_prior_defaults = b_data.get("prior_defaults", 0)
        source = "SEEDED_REGISTRY"
        provenance = f"Matched historical counterparty record for buyer '{invoice.buyer_name}'"

    if calc_supplier_months is None and s_norm in KNOWN_COUNTERPARTY_PROFILES:
        s_data = KNOWN_COUNTERPARTY_PROFILES[s_norm]
        calc_supplier_months = s_data.get("supplier_history_months")
        if source == "UNAVAILABLE":
            source = "SEEDED_REGISTRY"
            provenance = f"Matched supplier profile for '{invoice.supplier_name}'"

    return CounterpartyHistoricalProfile(
        buyer_rating=calc_buyer_rating,
        on_time_payment_ratio=calc_on_time_ratio,
        supplier_history_months=calc_supplier_months,
        prior_defaults=calc_prior_defaults,
        source=source,
        provenance_detail=provenance,
    )


def assess_risk(
    invoice: Invoice,
    verification: VerificationResult,
    existing_invoices: list[Invoice] | None = None,
) -> RiskAssessment:
    factors: list[RiskFactor] = []
    missing_info: list[str] = list(verification.uncertain_fields)
    score = RISK_POLICY_WEIGHTS["BASE_SCORE"]

    profile = invoice.counterparty_profile or resolve_counterparty_profile(invoice, existing_invoices)

    def factor(
        label: str,
        points: float,
        explanation: str,
        reason_code: str,
        source_category: RiskFactorSource = RiskFactorSource.POLICY_RULE,
    ):
        nonlocal score
        score += points
        impact = "negative" if points > 0 else "positive" if points < 0 else "neutral"
        factors.append(RiskFactor(
            label=label,
            points=round(points, 1),
            impact=impact,
            explanation=explanation,
            reason_code=reason_code,
            source_category=source_category,
        ))

    # 1. Buyer reliability (historical counterparty data)
    b_rating = invoice.buyer_rating if invoice.buyer_rating is not None else profile.buyer_rating
    if b_rating is not None:
        buyer_pts = RISK_POLICY_WEIGHTS["BUYER_RATING_MULTIPLIER"] * b_rating
        buyer_code = "BUYER_RELIABILITY_STRONG" if b_rating >= 0.75 else "BUYER_RELIABILITY_WEAK"
        factor(
            "Buyer reliability",
            buyer_pts,
            f"Buyer reliability signal is {b_rating:.0%} based on historical counterparty data.",
            buyer_code,
            source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY,
        )
    else:
        factor(
            "Buyer reliability",
            0.0,
            "Buyer reliability signal is unavailable — no historical counterparty record found.",
            "BUYER_RELIABILITY_UNKNOWN",
            source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY,
        )
        missing_info.append("buyer_historical_rating")

    # 2. Payment history (historical payment records)
    r = invoice.on_time_payment_ratio if invoice.on_time_payment_ratio is not None else profile.on_time_payment_ratio
    if r is not None:
        if r >= 0.95:
            factor("Payment history", -15.0, f"Exceptional on-time payment ratio of {r:.0%} based on historical payment records.", "PAYMENT_HISTORY_STRONG", source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
        elif r >= 0.90:
            factor("Payment history", -10.0, f"Strong on-time payment ratio of {r:.0%} based on historical payment records.", "PAYMENT_HISTORY_STRONG", source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
        elif r >= 0.85:
            factor("Payment history", -5.0, f"Acceptable on-time payment ratio of {r:.0%} based on historical payment records.", "PAYMENT_HISTORY_STRONG", source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
        elif r >= 0.70:
            factor("Payment history", 5.0, f"On-time payment ratio of {r:.0%} shows moderate payment delays based on historical payment records.", "PAYMENT_HISTORY_WEAK", source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
        elif r >= 0.50:
            factor("Payment history", 12.0, f"On-time payment ratio of {r:.0%} increases payment risk based on historical payment records.", "PAYMENT_HISTORY_WEAK", source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
        else:
            factor("Payment history", 20.0, f"On-time payment ratio of {r:.0%} reflects critical delinquency based on historical payment records.", "PAYMENT_HISTORY_CRITICAL", source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
    else:
        factor(
            "Payment history",
            0.0,
            "On-time payment history is unavailable based on historical payment records.",
            "PAYMENT_HISTORY_UNKNOWN",
            source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY,
        )
        missing_info.append("buyer_payment_history")

    # 3. Supplier operating history (supplier profile data)
    m = invoice.supplier_history_months if invoice.supplier_history_months is not None else profile.supplier_history_months
    if m is not None:
        if m < 6:
            factor("Supplier operating history", 12.0, f"New supplier with only {m} months of operating history based on supplier profile data.", "SUPPLIER_MATURITY_NEW", source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
        elif m < 12:
            factor("Supplier operating history", 8.0, f"Limited supplier history of {m} months based on supplier profile data.", "SUPPLIER_MATURITY_WEAK", source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
        elif m < 24:
            factor("Supplier operating history", 3.0, f"Developing supplier relationship with {m} months of history based on supplier profile data.", "SUPPLIER_MATURITY_WEAK", source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
        elif m < 36:
            factor("Supplier operating history", -5.0, f"Established supplier operating history of {m} months based on supplier profile data.", "SUPPLIER_MATURITY_STRONG", source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
        else:
            factor("Supplier operating history", -8.0, f"Mature supplier relationship with {m} months of history based on supplier profile data.", "SUPPLIER_MATURITY_STRONG", source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
    else:
        factor(
            "Supplier operating history",
            0.0,
            "Supplier operating history is unavailable based on supplier profile data.",
            "SUPPLIER_MATURITY_UNKNOWN",
            source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY,
        )
        missing_info.append("supplier_operating_history")

    # 4. Prior defaults (historical defaults record)
    d = invoice.prior_defaults if invoice.prior_defaults is not None else profile.prior_defaults
    if d is not None:
        if d > 0:
            pts = min(30.0, 15.0 * d)
            code = "PRIOR_DEFAULT" if d == 1 else "MULTIPLE_PRIOR_DEFAULTS"
            factor("Prior defaults", pts, f"{d} prior default(s) recorded in historical counterparty data.", code, source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
    else:
        factor(
            "Prior defaults",
            0.0,
            "Prior default history is unavailable.",
            "DEFAULT_HISTORY_UNKNOWN",
            source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY,
        )
        missing_info.append("prior_default_history")

    # 5. Invoice amount / concentration risk (invoice-derived)
    amt = invoice.amount
    if amt >= 10_000_000:
        factor("Large ticket", 12.0, f"Very large invoice size of ₹{amt:,.0f} extracted from invoice document creates high concentration risk.", "VERY_LARGE_INVOICE", source_category=RiskFactorSource.INVOICE_DERIVED)
    elif amt >= 5_000_000:
        factor("Large ticket", 8.0, f"Large invoice size of ₹{amt:,.0f} extracted from invoice document increases concentration risk.", "LARGE_INVOICE", source_category=RiskFactorSource.INVOICE_DERIVED)
    elif amt >= 2_500_000:
        factor("Large ticket", 4.0, f"Invoice amount of ₹{amt:,.0f} extracted from invoice document presents moderate concentration risk.", "LARGE_INVOICE", source_category=RiskFactorSource.INVOICE_DERIVED)
    elif amt >= 1_000_000:
        factor("Large ticket", 2.0, f"Invoice amount of ₹{amt:,.0f} extracted from invoice document presents low concentration risk.", "CONCENTRATION_RISK", source_category=RiskFactorSource.INVOICE_DERIVED)

    # 6. Invoice maturity / urgency (invoice-derived)
    today = date.today()
    if not invoice.due_date:
        factor(
            "Invoice maturity",
            0.0,
            "Due date unavailable from invoice document — maturity cannot be calculated.",
            "MATURITY_UNKNOWN",
            source_category=RiskFactorSource.INVOICE_DERIVED,
        )
    elif verification.status != VerificationStatus.REJECTED and invoice.due_date > today:
        days_until_due = (invoice.due_date - today).days
        if days_until_due <= 14:
            factor("Invoice maturity", RISK_POLICY_WEIGHTS["MATURITY_NEAR_DUE"], f"Invoice due date ({invoice.due_date}) indicates {days_until_due} days until due (urgent window).", "MATURITY_NEAR_DUE", source_category=RiskFactorSource.INVOICE_DERIVED)
        elif days_until_due <= 30:
            factor("Invoice maturity", RISK_POLICY_WEIGHTS["MATURITY_SHORT_TENOR"], f"Invoice due date ({invoice.due_date}) indicates {days_until_due} days until due (short tenor).", "MATURITY_SHORT_TENOR", source_category=RiskFactorSource.INVOICE_DERIVED)
        elif days_until_due <= 60:
            factor("Invoice maturity", RISK_POLICY_WEIGHTS["MATURITY_MEDIUM_TENOR"], f"Invoice due date ({invoice.due_date}) indicates {days_until_due} days until due (moderate tenor).", "MATURITY_MEDIUM_TENOR", source_category=RiskFactorSource.INVOICE_DERIVED)

    # 7. Verification uncertainty / rejection (verification-derived)
    if verification.status == VerificationStatus.PARTIALLY_VERIFIED:
        factor("Verification uncertainty", RISK_POLICY_WEIGHTS["VERIFICATION_UNCERTAIN"], "Missing fields from invoice document increase information asymmetry.", "VERIFICATION_UNCERTAIN", source_category=RiskFactorSource.VERIFICATION_CHECK)
    elif verification.status == VerificationStatus.REJECTED:
        factor("Verification rejected", RISK_POLICY_WEIGHTS["VERIFICATION_REJECTED"], "Invoice document failed deterministic verification policy.", "VERIFICATION_REJECTED", source_category=RiskFactorSource.VERIFICATION_CHECK)

    # 8. Duplicate invoice factor (verification-derived)
    if verification.duplicate_check and verification.duplicate_check.duplicate_detected:
        matched_no = verification.duplicate_check.matched_invoice_number or "prior invoice"
        factor("Duplicate invoice", RISK_POLICY_WEIGHTS["DUPLICATE_INVOICE"], f"Invoice matches prior submission {matched_no} across supplier, buyer, and amount.", "DUPLICATE_INVOICE", source_category=RiskFactorSource.VERIFICATION_CHECK)

    # 9. Amount consistency mismatch factor (invoice-derived)
    if "AMOUNT_MISMATCH" in verification.reason_codes:
        if invoice.subtotal is not None and invoice.tax_amount is not None:
            expected_total = round(invoice.subtotal + invoice.tax_amount, 2)
            diff = round(abs(expected_total - round(invoice.amount, 2)), 2)
            expl = f"Declared total ₹{invoice.amount:,.0f} differs from subtotal (₹{invoice.subtotal:,.0f}) + tax (₹{invoice.tax_amount:,.0f}) = ₹{expected_total:,.0f} by ₹{diff:,.0f}."
        else:
            expl = "Declared invoice total does not reconcile with subtotal plus tax."
        factor("Amount consistency mismatch", RISK_POLICY_WEIGHTS["AMOUNT_MISMATCH"], expl, "AMOUNT_MISMATCH", source_category=RiskFactorSource.INVOICE_DERIVED)

    # 10. GSTIN entity mismatch factor (invoice-derived)
    if "GSTIN_ENTITY_MISMATCH" in verification.reason_codes:
        expl = "GSTIN PAN entity structure is inconsistent with the supplier name provided in document."
        if verification.gstin_check and verification.gstin_check.warnings:
            for w in verification.gstin_check.warnings:
                if "indicates" in w.lower():
                    expl = w
                    break
        factor("GSTIN entity consistency", RISK_POLICY_WEIGHTS["GSTIN_ENTITY_MISMATCH"], expl, "GSTIN_ENTITY_MISMATCH", source_category=RiskFactorSource.INVOICE_DERIVED)

    # 11. GSTIN state mismatch factor (invoice-derived)
    if "GSTIN_STATE_MISMATCH" in verification.reason_codes:
        expl = "Supplier location is inconsistent with the GSTIN state code."
        if verification.gstin_check and verification.gstin_check.warnings:
            for w in verification.gstin_check.warnings:
                if "state" in w.lower():
                    expl = w
                    break
        factor("GSTIN state consistency", RISK_POLICY_WEIGHTS["GSTIN_STATE_MISMATCH"], expl, "GSTIN_STATE_MISMATCH", source_category=RiskFactorSource.INVOICE_DERIVED)

    score = round(max(0.0, min(100.0, score)), 1)
    band = RiskBand.LOW if score < 30 else RiskBand.MODERATE if score < 55 else RiskBand.HIGH if score < 75 else RiskBand.SEVERE
    confidence = round(0.96 - 0.08 * len(missing_info), 2)
    assessment = RiskAssessment(
        score=score,
        band=band,
        confidence=confidence,
        factors=factors,
        missing_information=missing_info,
    )
    assessment.summary = generate_risk_summary(assessment, invoice)
    return assessment


def generate_risk_summary(risk: RiskAssessment, invoice: Invoice | None = None) -> RiskDecisionSummary:
    """
    Generate a dynamic, structured explanation of the risk score from actual factor data.
    """
    reducers = [f for f in risk.factors if f.points < 0]
    reducers.sort(key=lambda f: f.points)  # Most negative first

    contributors = [f for f in risk.factors if f.points > 0]
    contributors.sort(key=lambda f: f.points, reverse=True)  # Largest positive first

    primary_drivers: list[str] = []
    for f in reducers:
        label = f.label
        if "buyer" in label.lower():
            primary_drivers.append(f"Strong buyer reliability reduced risk by {abs(f.points):.1f} points.")
        elif "payment" in label.lower():
            primary_drivers.append(f"Strong payment history reduced risk by {abs(f.points):.1f} points.")
        elif "supplier" in label.lower():
            primary_drivers.append(f"Established supplier history reduced risk by {abs(f.points):.1f} points.")
        else:
            primary_drivers.append(f"{label} reduced risk by {abs(f.points):.1f} points.")

    risk_contrib_msgs: list[str] = []
    for f in contributors:
        label = f.label
        if "maturity" in label.lower():
            risk_contrib_msgs.append(f"Invoice maturity added {f.points:.1f} points.")
        elif "large ticket" in label.lower() or "concentration" in label.lower():
            risk_contrib_msgs.append(f"Ticket concentration added {f.points:.1f} points.")
        elif "duplicate" in label.lower():
            risk_contrib_msgs.append(f"Duplicate invoice added {f.points:.1f} points.")
        elif "amount" in label.lower() and "mismatch" in label.lower():
            risk_contrib_msgs.append(f"Amount mismatch added {f.points:.1f} points.")
        elif "uncertainty" in label.lower():
            risk_contrib_msgs.append(f"Verification uncertainty added {f.points:.1f} points.")
        elif "gstin" in label.lower():
            risk_contrib_msgs.append(f"{label} added {f.points:.1f} points.")
        else:
            risk_contrib_msgs.append(f"{label} added {f.points:.1f} points.")

    # Human-readable decision explanation template
    if risk.band == RiskBand.LOW:
        if reducers:
            top_red = [r.label.lower() for r in reducers[:3]]
            if len(top_red) == 1:
                red_phrase = f"the {top_red[0]} is strong"
            elif len(top_red) == 2:
                red_phrase = f"the {top_red[0]} and {top_red[1]} are favorable"
            else:
                red_phrase = f"the buyer has strong reliability and payment history, while the supplier has an established operating history"
            explanation = f"This invoice is LOW risk ({risk.score}/100) primarily because {red_phrase}."
            if contributors:
                top_cont = [c.label.lower() for c in contributors[:2]]
                explanation += f" The remaining risk comes mainly from {' and '.join(top_cont)}."
        else:
            explanation = f"This invoice is LOW risk ({risk.score}/100) with a clean baseline profile."
    elif risk.band == RiskBand.MODERATE:
        contrib_phrase = ", ".join(c.label.lower() for c in contributors[:2]) if contributors else "baseline factors"
        red_phrase = ", ".join(r.label.lower() for r in reducers[:2]) if reducers else "general fundamentals"
        explanation = f"This invoice is MODERATE risk ({risk.score}/100). Favorable fundamentals ({red_phrase}) are balanced against elevated risk factors ({contrib_phrase})."
    elif risk.band == RiskBand.HIGH:
        contrib_phrase = ", ".join(c.label.lower() for c in contributors[:3]) if contributors else "elevated risk factors"
        explanation = f"This invoice is HIGH risk ({risk.score}/100), driven primarily by significant risk factors: {contrib_phrase}."
    else:  # SEVERE
        contrib_phrase = ", ".join(c.label.lower() for c in contributors[:3]) if contributors else "critical risk factors"
        explanation = f"This invoice is SEVERE risk ({risk.score}/100), driven by critical risk triggers: {contrib_phrase}."

    return RiskDecisionSummary(
        score=risk.score,
        band=risk.band,
        primary_drivers=primary_drivers,
        risk_contributors=risk_contrib_msgs,
        top_risk_contributors=contributors,
        top_risk_reducers=reducers,
        human_readable_explanation=explanation,
    )


def simulate_risk_change(
    invoice: Invoice,
    verification: VerificationResult,
    simulation: RiskSimulationRequest,
) -> RiskSimulationResult:
    """
    Deterministically simulate risk score changes under what-if condition overrides.
    Reuses the exact same scoring weights, thresholds, and band rules as assess_risk.
    Does NOT mutate invoice, verification, or Risk Ledger state.
    """
    original_assessment = assess_risk(invoice, verification)
    sim_factors: list[RiskFactor] = []
    score = RISK_POLICY_WEIGHTS["BASE_SCORE"]
    modified_factors: list[RiskFactor] = []

    profile = invoice.counterparty_profile or resolve_counterparty_profile(invoice)

    def sim_factor(
        label: str,
        points: float,
        explanation: str,
        reason_code: str,
        is_modified: bool = False,
        source_category: RiskFactorSource = RiskFactorSource.POLICY_RULE,
    ):
        nonlocal score
        score += points
        impact = "negative" if points > 0 else "positive" if points < 0 else "neutral"
        rf = RiskFactor(
            label=label,
            points=round(points, 1),
            impact=impact,
            explanation=explanation,
            reason_code=reason_code,
            source_category=source_category,
        )
        sim_factors.append(rf)
        if is_modified:
            modified_factors.append(rf)

    # 1. Buyer reliability
    sim_buyer_rating = simulation.simulated_buyer_rating if simulation.simulated_buyer_rating is not None else (invoice.buyer_rating if invoice.buyer_rating is not None else profile.buyer_rating)
    if sim_buyer_rating is not None:
        buyer_pts = RISK_POLICY_WEIGHTS["BUYER_RATING_MULTIPLIER"] * sim_buyer_rating
        buyer_code = "BUYER_RELIABILITY_STRONG" if sim_buyer_rating >= 0.75 else "BUYER_RELIABILITY_WEAK"
        sim_factor("Buyer reliability", buyer_pts, f"Buyer reliability signal is {sim_buyer_rating:.0%} based on historical counterparty data.", buyer_code, is_modified=simulation.simulated_buyer_rating is not None, source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
    else:
        sim_factor("Buyer reliability", 0.0, "Buyer reliability signal is unavailable — no historical counterparty record found.", "BUYER_RELIABILITY_UNKNOWN", is_modified=False, source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)

    # 2. Payment history
    r = simulation.simulated_on_time_payment_ratio if simulation.simulated_on_time_payment_ratio is not None else (invoice.on_time_payment_ratio if invoice.on_time_payment_ratio is not None else profile.on_time_payment_ratio)
    is_pmt_mod = simulation.simulated_on_time_payment_ratio is not None
    if r is not None:
        if r >= 0.95:
            sim_factor("Payment history", -15.0, f"Exceptional on-time payment ratio of {r:.0%} based on historical payment records.", "PAYMENT_HISTORY_STRONG", is_modified=is_pmt_mod, source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
        elif r >= 0.90:
            sim_factor("Payment history", -10.0, f"Strong on-time payment ratio of {r:.0%} based on historical payment records.", "PAYMENT_HISTORY_STRONG", is_modified=is_pmt_mod, source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
        elif r >= 0.85:
            sim_factor("Payment history", -5.0, f"Acceptable on-time payment ratio of {r:.0%} based on historical payment records.", "PAYMENT_HISTORY_STRONG", is_modified=is_pmt_mod, source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
        elif r >= 0.70:
            sim_factor("Payment history", 5.0, f"On-time payment ratio of {r:.0%} shows moderate payment delays based on historical payment records.", "PAYMENT_HISTORY_WEAK", is_modified=is_pmt_mod, source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
        elif r >= 0.50:
            sim_factor("Payment history", 12.0, f"On-time payment ratio of {r:.0%} increases payment risk based on historical payment records.", "PAYMENT_HISTORY_WEAK", is_modified=is_pmt_mod, source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
        else:
            sim_factor("Payment history", 20.0, f"On-time payment ratio of {r:.0%} reflects critical delinquency based on historical payment records.", "PAYMENT_HISTORY_CRITICAL", is_modified=is_pmt_mod, source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
    else:
        sim_factor("Payment history", 0.0, "On-time payment history is unavailable based on historical payment records.", "PAYMENT_HISTORY_UNKNOWN", is_modified=False, source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)

    # 3. Supplier operating history
    m = simulation.simulated_supplier_history_months if simulation.simulated_supplier_history_months is not None else (invoice.supplier_history_months if invoice.supplier_history_months is not None else profile.supplier_history_months)
    is_sup_mod = simulation.simulated_supplier_history_months is not None
    if m is not None:
        if m < 6:
            sim_factor("Supplier operating history", 12.0, f"New supplier with only {m} months of operating history based on supplier profile data.", "SUPPLIER_MATURITY_NEW", is_modified=is_sup_mod, source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
        elif m < 12:
            sim_factor("Supplier operating history", 8.0, f"Limited supplier history of {m} months based on supplier profile data.", "SUPPLIER_MATURITY_WEAK", is_modified=is_sup_mod, source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
        elif m < 24:
            sim_factor("Supplier operating history", 3.0, f"Developing supplier relationship with {m} months of history based on supplier profile data.", "SUPPLIER_MATURITY_WEAK", is_modified=is_sup_mod, source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
        elif m < 36:
            sim_factor("Supplier operating history", -5.0, f"Established supplier operating history of {m} months based on supplier profile data.", "SUPPLIER_MATURITY_STRONG", is_modified=is_sup_mod, source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
        else:
            sim_factor("Supplier operating history", -8.0, f"Mature supplier relationship with {m} months of history based on supplier profile data.", "SUPPLIER_MATURITY_STRONG", is_modified=is_sup_mod, source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
    else:
        sim_factor("Supplier operating history", 0.0, "Supplier operating history is unavailable based on supplier profile data.", "SUPPLIER_MATURITY_UNKNOWN", is_modified=False, source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)

    # 4. Prior defaults
    d = simulation.simulated_prior_defaults if simulation.simulated_prior_defaults is not None else (invoice.prior_defaults if invoice.prior_defaults is not None else profile.prior_defaults)
    if d is not None and d > 0:
        pts = min(30.0, 15.0 * d)
        code = "PRIOR_DEFAULT" if d == 1 else "MULTIPLE_PRIOR_DEFAULTS"
        sim_factor("Prior defaults", pts, f"{d} prior default(s) recorded in historical counterparty data.", code, is_modified=simulation.simulated_prior_defaults is not None, source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)
    elif d is None:
        sim_factor("Prior defaults", 0.0, "Prior default history is unavailable.", "DEFAULT_HISTORY_UNKNOWN", is_modified=False, source_category=RiskFactorSource.HISTORICAL_COUNTERPARTY)

    # 5. Large ticket / amount concentration
    amt = simulation.simulated_amount if simulation.simulated_amount is not None else invoice.amount
    is_amt_mod = simulation.simulated_amount is not None
    if amt >= 10_000_000:
        sim_factor("Large ticket", 12.0, f"Very large invoice size of ₹{amt:,.0f} extracted from invoice creates high concentration risk.", "VERY_LARGE_INVOICE", is_modified=is_amt_mod, source_category=RiskFactorSource.INVOICE_DERIVED)
    elif amt >= 5_000_000:
        sim_factor("Large ticket", 8.0, f"Large invoice size of ₹{amt:,.0f} extracted from invoice increases concentration risk.", "LARGE_INVOICE", is_modified=is_amt_mod, source_category=RiskFactorSource.INVOICE_DERIVED)
    elif amt >= 2_500_000:
        sim_factor("Large ticket", 4.0, f"Invoice amount of ₹{amt:,.0f} extracted from invoice presents moderate concentration risk.", "LARGE_INVOICE", is_modified=is_amt_mod, source_category=RiskFactorSource.INVOICE_DERIVED)
    elif amt >= 1_000_000:
        sim_factor("Large ticket", 2.0, f"Invoice amount of ₹{amt:,.0f} extracted from invoice presents low concentration risk.", "CONCENTRATION_RISK", is_modified=is_amt_mod, source_category=RiskFactorSource.INVOICE_DERIVED)

    # 6. Invoice maturity
    today = date.today()
    if simulation.simulated_days_until_due is not None:
        days = simulation.simulated_days_until_due
        if days <= 14:
            sim_factor("Invoice maturity", RISK_POLICY_WEIGHTS["MATURITY_NEAR_DUE"], f"Invoice is due in {days} days, increasing repayment-urgency risk.", "MATURITY_NEAR_DUE", is_modified=True, source_category=RiskFactorSource.INVOICE_DERIVED)
        elif days <= 30:
            sim_factor("Invoice maturity", RISK_POLICY_WEIGHTS["MATURITY_SHORT_TENOR"], f"Invoice is due in {days} days, short tenor window.", "MATURITY_SHORT_TENOR", is_modified=True, source_category=RiskFactorSource.INVOICE_DERIVED)
        elif days <= 60:
            sim_factor("Invoice maturity", RISK_POLICY_WEIGHTS["MATURITY_MEDIUM_TENOR"], f"Invoice is due in {days} days, moderate tenor window.", "MATURITY_MEDIUM_TENOR", is_modified=True, source_category=RiskFactorSource.INVOICE_DERIVED)
        else:
            sim_factor("Invoice maturity", 0.0, f"Invoice is due in {days} days (>60 days), low maturity urgency.", "MATURITY_LONG_TENOR", is_modified=True, source_category=RiskFactorSource.INVOICE_DERIVED)
    elif not invoice.due_date:
        sim_factor("Invoice maturity", 0.0, "Due date unavailable from invoice — maturity cannot be calculated.", "MATURITY_UNKNOWN", source_category=RiskFactorSource.INVOICE_DERIVED)
    elif verification.status != VerificationStatus.REJECTED and invoice.due_date > today:
        days = (invoice.due_date - today).days
        if days <= 14:
            sim_factor("Invoice maturity", RISK_POLICY_WEIGHTS["MATURITY_NEAR_DUE"], f"Invoice is due in {days} days, increasing repayment-urgency risk.", "MATURITY_NEAR_DUE", source_category=RiskFactorSource.INVOICE_DERIVED)
        elif days <= 30:
            sim_factor("Invoice maturity", RISK_POLICY_WEIGHTS["MATURITY_SHORT_TENOR"], f"Invoice is due in {days} days, short tenor window.", "MATURITY_SHORT_TENOR", source_category=RiskFactorSource.INVOICE_DERIVED)
        elif days <= 60:
            sim_factor("Invoice maturity", RISK_POLICY_WEIGHTS["MATURITY_MEDIUM_TENOR"], f"Invoice is due in {days} days, moderate tenor window.", "MATURITY_MEDIUM_TENOR", source_category=RiskFactorSource.INVOICE_DERIVED)

    # 7. Verification status
    v_status = simulation.simulated_verification_status or verification.status
    is_ver_mod = simulation.simulated_verification_status is not None
    if v_status == VerificationStatus.PARTIALLY_VERIFIED:
        sim_factor("Verification uncertainty", RISK_POLICY_WEIGHTS["VERIFICATION_UNCERTAIN"], "Missing fields increase information asymmetry.", "VERIFICATION_UNCERTAIN", is_modified=is_ver_mod, source_category=RiskFactorSource.VERIFICATION_CHECK)
    elif v_status == VerificationStatus.REJECTED:
        sim_factor("Verification rejected", RISK_POLICY_WEIGHTS["VERIFICATION_REJECTED"], "Invoice failed the synthetic verification policy.", "VERIFICATION_REJECTED", is_modified=is_ver_mod, source_category=RiskFactorSource.VERIFICATION_CHECK)

    # 8. Duplicate invoice
    if simulation.simulate_duplicate is not None:
        is_dup = simulation.simulate_duplicate
        is_dup_mod = True
    else:
        is_dup = bool(verification.duplicate_check and verification.duplicate_check.duplicate_detected)
        is_dup_mod = False
    if is_dup:
        matched_no = (verification.duplicate_check.matched_invoice_number if verification.duplicate_check else None) or "simulated duplicate"
        sim_factor("Duplicate invoice", RISK_POLICY_WEIGHTS["DUPLICATE_INVOICE"], f"Invoice matches prior submission {matched_no}.", "DUPLICATE_INVOICE", is_modified=is_dup_mod, source_category=RiskFactorSource.VERIFICATION_CHECK)

    # 9. Amount consistency mismatch
    if "AMOUNT_MISMATCH" in verification.reason_codes:
        sim_factor("Amount consistency mismatch", RISK_POLICY_WEIGHTS["AMOUNT_MISMATCH"], "Declared invoice total does not reconcile with subtotal plus tax.", "AMOUNT_MISMATCH", source_category=RiskFactorSource.INVOICE_DERIVED)

    # 10. GSTIN entity mismatch
    if "GSTIN_ENTITY_MISMATCH" in verification.reason_codes:
        sim_factor("GSTIN entity consistency", RISK_POLICY_WEIGHTS["GSTIN_ENTITY_MISMATCH"], "GSTIN PAN entity structure is inconsistent with supplier name.", "GSTIN_ENTITY_MISMATCH", source_category=RiskFactorSource.INVOICE_DERIVED)

    # 11. GSTIN state mismatch
    if "GSTIN_STATE_MISMATCH" in verification.reason_codes:
        sim_factor("GSTIN state consistency", RISK_POLICY_WEIGHTS["GSTIN_STATE_MISMATCH"], "Supplier location is inconsistent with GSTIN state code.", "GSTIN_STATE_MISMATCH", source_category=RiskFactorSource.INVOICE_DERIVED)

    sim_score = round(max(0.0, min(100.0, score)), 1)
    sim_band = RiskBand.LOW if sim_score < 30 else RiskBand.MODERATE if sim_score < 55 else RiskBand.HIGH if sim_score < 75 else RiskBand.SEVERE
    delta = round(sim_score - original_assessment.score, 1)

    # Generate scenario-specific explanation
    scenario_title = simulation.scenario_name or "Custom Simulation"
    if simulation.simulate_duplicate is True:
        scenario_title = "Duplicate Invoice Scenario"
        expl = f"Adding the duplicate-invoice factor increases the score by {RISK_POLICY_WEIGHTS['DUPLICATE_INVOICE']:.0f} points."
    elif simulation.simulated_on_time_payment_ratio is not None:
        scenario_title = f"Payment History ({simulation.simulated_on_time_payment_ratio:.0%}) Scenario"
        expl = f"Changing on-time payment ratio to {simulation.simulated_on_time_payment_ratio:.0%} shifts the score by {delta:+0.1f} points (Band: {sim_band.value})."
    elif simulation.simulated_amount is not None:
        scenario_title = f"Invoice Amount (₹{simulation.simulated_amount:,.0f}) Scenario"
        expl = f"Adjusting invoice amount to ₹{simulation.simulated_amount:,.0f} changes ticket concentration by {delta:+0.1f} points (Band: {sim_band.value})."
    elif simulation.simulated_days_until_due is not None:
        scenario_title = f"Maturity Tenor ({simulation.simulated_days_until_due} days) Scenario"
        expl = f"Adjusting maturity window to {simulation.simulated_days_until_due} days changes urgency points by {delta:+0.1f} points (Band: {sim_band.value})."
    elif simulation.simulated_verification_status is not None:
        scenario_title = f"Verification Status ({simulation.simulated_verification_status.value}) Scenario"
        expl = f"Simulating verification as {simulation.simulated_verification_status.value} alters verification penalty by {delta:+0.1f} points (Band: {sim_band.value})."
    else:
        sign = "+" if delta >= 0 else ""
        expl = f"Simulated changes result in a {sign}{delta:.1f} point change (New score: {sim_score}/100, Band: {sim_band.value})."

    return RiskSimulationResult(
        scenario_name=scenario_title,
        original_score=original_assessment.score,
        original_band=original_assessment.band,
        simulated_score=sim_score,
        simulated_band=sim_band,
        score_delta=delta,
        explanation=expl,
        modified_factors=modified_factors,
    )


def get_standard_what_if_scenarios(
    invoice: Invoice,
    verification: VerificationResult,
) -> list[RiskSimulationResult]:
    """
    Generate preset standard what-if analysis scenarios for the given invoice and verification result.
    """
    scenarios: list[RiskSimulationResult] = []

    # 1. Duplicate invoice scenario
    scenarios.append(simulate_risk_change(
        invoice,
        verification,
        RiskSimulationRequest(scenario_name="Duplicate Invoice Detected", simulate_duplicate=True),
    ))

    # 2. Lower payment history (60%)
    scenarios.append(simulate_risk_change(
        invoice,
        verification,
        RiskSimulationRequest(scenario_name="Lower On-Time Payment History (60%)", simulated_on_time_payment_ratio=0.60),
    ))

    # 3. High amount / Large ticket (₹5,000,000)
    scenarios.append(simulate_risk_change(
        invoice,
        verification,
        RiskSimulationRequest(scenario_name="Higher Invoice Amount (₹5,000,000)", simulated_amount=5000000.0),
    ))

    # 4. Urgent maturity (10 days)
    if invoice.due_date:
        scenarios.append(simulate_risk_change(
            invoice,
            verification,
            RiskSimulationRequest(scenario_name="Urgent Maturity Tenor (10 days)", simulated_days_until_due=10),
        ))
    else:
        scenarios.append(simulate_risk_change(
            invoice,
            verification,
            RiskSimulationRequest(scenario_name="Urgent Maturity Tenor (10 days)", simulated_days_until_due=10),
        ))

    # 5. Verification uncertainty (+12)
    if verification.status == VerificationStatus.VERIFIED:
        scenarios.append(simulate_risk_change(
            invoice,
            verification,
            RiskSimulationRequest(scenario_name="Verification Uncertainty", simulated_verification_status=VerificationStatus.PARTIALLY_VERIFIED),
        ))

    return scenarios


def evaluate(invoice: Invoice, existing_invoices: list[Invoice] | None = None) -> InvoiceEvaluation:
    verification = verify_invoice(invoice, existing_invoices)
    return InvoiceEvaluation(verification=verification, risk=assess_risk(invoice, verification))


def create_risk_ledger_entry(
    invoice: Invoice,
    opportunity_id: str | None = None,
    evaluation: InvoiceEvaluation | None = None,
    entry_id: str | None = None,
    source: str | None = None,
    source_filename: str | None = None,
    existing_invoices: list[Invoice] | None = None,
) -> RiskLedgerEntry:
    if evaluation is None:
        evaluation = evaluate(invoice, existing_invoices)
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
        source=source,
        source_filename=source_filename,
    )

