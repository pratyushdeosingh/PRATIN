"""Deterministic PDF invoice text extraction and field identification."""
from __future__ import annotations

import io
import re
from datetime import date, datetime, timedelta
from typing import Literal

from contracts.models import (
    ExtractedInvoiceFields,
    ExtractionConfidence,
    Invoice,
    InvoiceEvaluation,
    InvoiceParseResponse,
    RiskLedgerEntry,
)
from services.invoice_risk.engine import create_risk_ledger_entry, evaluate

MAX_PDF_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def extract_text_from_pdf(pdf_bytes: bytes) -> tuple[str, str | None]:
    """Extracts raw text from a PDF in memory.
    
    Returns (text, error_code). Error codes: PDF_INVALID, PDF_EMPTY, PDF_TEXT_UNREADABLE.
    """
    if not pdf_bytes:
        return "", "PDF_EMPTY"
    if len(pdf_bytes) > MAX_PDF_SIZE_BYTES:
        return "", "PDF_INVALID"
    if not pdf_bytes.startswith(b"%PDF-"):
        return "", "PDF_INVALID"

    text_parts: list[str] = []

    # 1. Try PyMuPDF (fitz)
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if doc.page_count == 0:
            return "", "PDF_EMPTY"
        for page in doc:
            page_text = page.get_text()
            if page_text:
                text_parts.append(page_text)
    except Exception:
        text_parts = []

    # 2. Fallback to pypdf if fitz didn't yield text
    if not text_parts:
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(pdf_bytes))
            if len(reader.pages) == 0:
                return "", "PDF_EMPTY"
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text_parts.append(extracted)
        except Exception:
            pass

    full_text = "\n".join(text_parts).strip()
    if not full_text:
        return "", "PDF_TEXT_UNREADABLE"

    return full_text, None


def _parse_date(date_str: str) -> date | None:
    """Normalizes various invoice date string formats to a date object."""
    cleaned = date_str.strip().rstrip(".,;")
    formats = [
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d.%m.%Y",
        "%m/%d/%Y",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%Y/%m/%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def parse_extracted_text(text: str) -> ExtractedInvoiceFields:
    """Parses extracted PDF text into structured invoice fields using deterministic heuristics."""
    warnings: list[str] = []

    # 1. Invoice Number
    invoice_number: str | None = None
    inv_patterns = [
        r'(?i)(?:invoice\s*(?:number|no\.?|#|id)|bill\s*(?:no\.?|#|number))\s*[:\-\s#]\s*([A-Z0-9\-_/]+)',
        r'(?i)\b(INV-[A-Z0-9\-_/]+)\b',
    ]
    for p in inv_patterns:
        match = re.search(p, text)
        if match:
            invoice_number = match.group(1).strip().rstrip(".,;")
            break

    # 2. Supplier Name
    supplier_name: str | None = None
    sup_patterns = [
        r'(?i)(?:supplier(?:\s*name)?|vendor(?:\s*name)?|seller|from|billed\s+by|issued\s+by)\s*[:\-\s]\s*([^\n\r,;]+)',
    ]
    for p in sup_patterns:
        match = re.search(p, text)
        if match:
            candidate = match.group(1).strip()
            if candidate and len(candidate) > 1:
                supplier_name = candidate
                break

    # 3. Buyer Name
    buyer_name: str | None = None
    buy_patterns = [
        r'(?i)(?:buyer(?:\s*name)?|customer(?:\s*name)?|client|bill\s+to|sold\s+to|to)\s*[:\-\s]\s*([^\n\r,;]+)',
    ]
    for p in buy_patterns:
        match = re.search(p, text)
        if match:
            candidate = match.group(1).strip()
            if candidate and len(candidate) > 1 and candidate != supplier_name:
                buyer_name = candidate
                break

    # 4. Amount
    amount: float | None = None
    amt_patterns = [
        r'(?i)\b(?:total\s+amount|grand\s+total|amount\s+due|invoice\s+(?:total|amount)|net\s+payable|balance\s+due)\b\s*[:\-\s]*(?:INR|RS|₹)?[\s\.]*([0-9,]+(?:\.[0-9]{1,2})?)',
        r'(?i)\b(?:total)\b\s*[:\-\s]*(?:INR|RS|₹)?[\s\.]*([0-9,]+(?:\.[0-9]{1,2})?)',
        r'[₹]\s*([0-9,]+(?:\.[0-9]{1,2})?)',
        r'(?i)\bINR\s*([0-9,]+(?:\.[0-9]{1,2})?)\b',
    ]
    for p in amt_patterns:
        match = re.search(p, text)
        if match:
            raw_amt = match.group(1).replace(",", "").strip()
            try:
                val = float(raw_amt)
                if val > 0:
                    amount = val
                    break
            except ValueError:
                pass

    # 5. Issue Date
    issue_date: date | None = None
    issue_patterns = [
        r'(?i)(?:invoice\s*date|issue\s*date|date\s*of\s*issue|bill\s*date|dated|date)\s*[:\-\s]\s*([0-9]{1,4}[/\-\.][0-9]{1,2}[/\-\.][0-9]{1,4}|[0-9]{1,2}\s+[A-Za-z]{3,9}\s+[0-9]{4}|[A-Za-z]{3,9}\s+[0-9]{1,2},\s*[0-9]{4})',
    ]
    for p in issue_patterns:
        match = re.search(p, text)
        if match:
            parsed = _parse_date(match.group(1))
            if parsed:
                issue_date = parsed
                break

    # 6. Due Date & Payment Terms
    due_date: date | None = None
    due_patterns = [
        r'(?i)(?:due\s*date|payment\s*due|valid\s*(?:until|to)|payment\s*date)\s*[:\-\s]\s*([0-9]{1,4}[/\-\.][0-9]{1,2}[/\-\.][0-9]{1,4}|[0-9]{1,2}\s+[A-Za-z]{3,9}\s+[0-9]{4}|[A-Za-z]{3,9}\s+[0-9]{1,2},\s*[0-9]{4})',
    ]
    for p in due_patterns:
        match = re.search(p, text)
        if match:
            parsed = _parse_date(match.group(1))
            if parsed:
                due_date = parsed
                break

    payment_terms: str | None = None
    terms_match = re.search(r'(?i)(?:payment\s*terms|terms)\s*[:\-\s]\s*(net\s*\d+|\d+\s*days)', text)
    if terms_match:
        payment_terms = terms_match.group(1).strip()
        if not due_date and issue_date:
            days_match = re.search(r'\d+', payment_terms)
            if days_match:
                days = int(days_match.group(0))
                due_date = issue_date + timedelta(days=days)

    # 7. GSTIN
    gstin: str | None = None
    gstin_patterns = [
        r'(?i)(?:gstin|gst\s*(?:no\.?|number|id)?)\s*[:\-\s]\s*([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}|[A-Z0-9]{15})',
        r'\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1})\b',
    ]
    for p in gstin_patterns:
        match = re.search(p, text)
        if match:
            gstin = match.group(1).strip().upper()
            break

    # 8. Purchase Order Reference
    purchase_order_reference: str | None = None
    po_patterns = [
        r'(?i)(?:po\s*(?:number|no\.?|#|ref)?|purchase\s*order(?:\s*(?:no\.?|#|number|ref))?)\s*[:\-\s]\s*([A-Z0-9\-_/]+)',
        r'(?i)\b(PO-[A-Z0-9\-_/]+)\b',
    ]
    for p in po_patterns:
        match = re.search(p, text)
        if match:
            purchase_order_reference = match.group(1).strip().rstrip(".,;")
            break

    # 9. Subtotal
    subtotal: float | None = None
    subtotal_patterns = [
        r'(?i)\b(?:subtotal|sub\s*total|net\s*amount)\b\s*[:\-\s]*(?:INR|RS|₹)?[\s\.]*([0-9,]+(?:\.[0-9]{1,2})?)',
    ]
    for p in subtotal_patterns:
        match = re.search(p, text)
        if match:
            raw_amt = match.group(1).replace(",", "").strip()
            try:
                val = float(raw_amt)
                if val > 0:
                    subtotal = val
                    break
            except ValueError:
                pass

    # 10. Tax Amount
    tax_amount: float | None = None
    tax_patterns = [
        r'(?i)\b(?:tax|vat|gst|igst|cgst\s*\+\s*sgst|tax\s*amount)\b(?:\s*\([^\)]*\))?\s*[:\-\s]*(?:INR|RS|₹)?[\s\.]*([0-9,]+(?:\.[0-9]{1,2})?)',
    ]
    for p in tax_patterns:
        match = re.search(p, text)
        if match:
            raw_amt = match.group(1).replace(",", "").strip()
            try:
                val = float(raw_amt)
                if val >= 0:
                    tax_amount = val
                    break
            except ValueError:
                pass

    # 11. Supplier State
    supplier_state: str | None = None
    state_patterns = [
        r'(?i)(?:supplier\s*state|place\s*of\s*supply|state)\s*[:\-\s]\s*([A-Za-z\s]+)',
    ]
    for p in state_patterns:
        match = re.search(p, text)
        if match:
            cand = match.group(1).strip()
            if cand:
                supplier_state = cand.split("\n")[0].strip()
                break

    # Compute missing fields & extraction confidence
    missing_fields: list[str] = []
    if not invoice_number:
        missing_fields.append("invoice_number")
    if not supplier_name:
        missing_fields.append("supplier_name")
    if not buyer_name:
        missing_fields.append("buyer_name")
    if amount is None:
        missing_fields.append("amount")
    if not issue_date:
        missing_fields.append("issue_date")
    if not due_date:
        missing_fields.append("due_date")
    if not gstin:
        missing_fields.append("gstin")
    if not purchase_order_reference:
        missing_fields.append("purchase_order_reference")

    core_missing = [f for f in missing_fields if f not in ("gstin", "purchase_order_reference")]
    if not missing_fields:
        confidence = ExtractionConfidence.HIGH
    elif not core_missing:
        confidence = ExtractionConfidence.MEDIUM
    else:
        confidence = ExtractionConfidence.LOW
        warnings.append(f"Core invoice fields missing: {', '.join(core_missing)}.")

    return ExtractedInvoiceFields(
        invoice_number=invoice_number,
        supplier_name=supplier_name,
        buyer_name=buyer_name,
        amount=amount,
        currency="INR",
        issue_date=issue_date,
        due_date=due_date,
        gstin=gstin,
        purchase_order_reference=purchase_order_reference,
        payment_terms=payment_terms,
        subtotal=subtotal,
        tax_amount=tax_amount,
        supplier_state=supplier_state,
        missing_fields=missing_fields,
        warnings=warnings,
        extraction_confidence=confidence,
    )


def parse_and_evaluate_pdf(
    pdf_bytes: bytes,
    filename: str = "invoice.pdf",
    existing_invoices: list[Invoice] | None = None,
) -> InvoiceParseResponse:
    """Extracts text from a PDF, parses fields, and connects cleanly into existing verification and risk engine."""
    text, error = extract_text_from_pdf(pdf_bytes)
    if error:
        detail = (
            "Scanned or image-only PDF detected. OCR is not supported; text-based PDF is required."
            if error == "PDF_TEXT_UNREADABLE"
            else "The uploaded PDF is empty."
            if error == "PDF_EMPTY"
            else "Invalid PDF file or unsupported format."
        )
        return InvoiceParseResponse(
            status=error,  # type: ignore
            extracted_fields=None,
            invoice=None,
            evaluation=None,
            ledger_entry=None,
            error_detail=detail,
        )

    extracted = parse_extracted_text(text)

    # If essential core fields were extracted, construct Invoice and run existing verification & risk engine
    if (
        extracted.invoice_number
        and extracted.supplier_name
        and extracted.buyer_name
        and extracted.amount
    ):
        try:
            inv = Invoice(
                invoice_number=extracted.invoice_number,
                supplier_name=extracted.supplier_name,
                buyer_name=extracted.buyer_name,
                amount=extracted.amount,
                currency="INR",
                issue_date=extracted.issue_date,
                due_date=extracted.due_date,
                industry="Manufacturing",
                gstin=extracted.gstin,
                purchase_order_reference=extracted.purchase_order_reference,
                subtotal=extracted.subtotal,
                tax_amount=extracted.tax_amount,
                supplier_state=extracted.supplier_state,
            )
            from .engine import resolve_counterparty_profile
            inv.counterparty_profile = resolve_counterparty_profile(inv, existing_invoices)
            eval_res = evaluate(inv, existing_invoices)
            # Update provenance to indicate SERVICE
            eval_res = eval_res.model_copy(update={"provenance": "SERVICE"})
            ledger_entry = create_risk_ledger_entry(
                invoice=inv,
                evaluation=eval_res,
                source="PDF_UPLOAD",
                source_filename=filename,
                existing_invoices=existing_invoices,
            )
            return InvoiceParseResponse(
                status="SUCCESS",
                extracted_fields=extracted,
                invoice=inv,
                evaluation=eval_res,
                ledger_entry=ledger_entry,
                error_detail=None,
            )
        except Exception as ex:
            extracted.warnings.append(f"Invoice model validation failed: {str(ex)}")

    return InvoiceParseResponse(
        status="SUCCESS",
        extracted_fields=extracted,
        invoice=None,
        evaluation=None,
        ledger_entry=None,
        error_detail="Invoice extracted partially; some required fields were missing from the document.",
    )
