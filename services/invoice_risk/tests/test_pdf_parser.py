"""Comprehensive deterministic test suite for PDF invoice extraction and verification pipeline."""
import io
from datetime import date
import pytest
from fastapi.testclient import TestClient
import fitz  # PyMuPDF

from contracts.models import ExtractionConfidence, VerificationStatus
from services.invoice_risk.app import app
from services.invoice_risk.pdf_parser import (
    extract_text_from_pdf,
    parse_and_evaluate_pdf,
    parse_extracted_text,
)

client = TestClient(app)


def make_pdf(text: str) -> bytes:
    """Helper to create an in-memory PDF with specified text using PyMuPDF."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), text, fontsize=11)
    buf = doc.tobytes()
    doc.close()
    return buf


def test_valid_invoice_pdf_extraction():
    sample_text = """
    TAX INVOICE
    Invoice Number: INV-2026-9901
    Supplier Name: Apex Heavy Castings Ltd
    Buyer Name: Zenon Automotives Pvt Ltd
    Invoice Date: 2026-08-20
    Due Date: 2026-10-15
    Total Amount: INR 2,450,000.00
    GSTIN: 27ABCDE1234F1Z5
    Purchase Order: PO-2026-8812
    Payment Terms: Net 45 Days
    """
    pdf_bytes = make_pdf(sample_text)
    res = parse_and_evaluate_pdf(pdf_bytes, filename="apex_inv.pdf")

    assert res.status == "SUCCESS"
    assert res.extracted_fields is not None
    assert res.extracted_fields.invoice_number == "INV-2026-9901"
    assert res.extracted_fields.supplier_name == "Apex Heavy Castings Ltd"
    assert res.extracted_fields.buyer_name == "Zenon Automotives Pvt Ltd"
    assert res.extracted_fields.amount == 2450000.0
    assert res.extracted_fields.issue_date == date(2026, 8, 20)
    assert res.extracted_fields.due_date == date(2026, 10, 15)
    assert res.extracted_fields.gstin == "27ABCDE1234F1Z5"
    assert res.extracted_fields.purchase_order_reference == "PO-2026-8812"
    assert res.extracted_fields.extraction_confidence == ExtractionConfidence.HIGH
    assert len(res.extracted_fields.missing_fields) == 0

    # Verification & Risk Ledger integration
    assert res.invoice is not None
    assert res.evaluation is not None
    assert res.evaluation.verification.status == VerificationStatus.VERIFIED
    assert res.ledger_entry is not None
    assert res.ledger_entry.source == "PDF_UPLOAD"
    assert res.ledger_entry.source_filename == "apex_inv.pdf"
    assert len(res.ledger_entry.risk.factors) > 0


def test_different_label_variations():
    sample_text = """
    Bill No: BILL-88219
    Vendor: Shakti Precision Gears
    Customer: Bharat Motors Corp
    Dated: 15/08/2026
    Payment Due: 30/09/2026
    Grand Total: Rs. 1,250,000
    GST No: 27ABCDE1234F1Z5
    PO Number: PO-SHAKTI-441
    """
    pdf_bytes = make_pdf(sample_text)
    res = parse_and_evaluate_pdf(pdf_bytes, filename="bill.pdf")

    assert res.status == "SUCCESS"
    assert res.extracted_fields.invoice_number == "BILL-88219"
    assert res.extracted_fields.supplier_name == "Shakti Precision Gears"
    assert res.extracted_fields.buyer_name == "Bharat Motors Corp"
    assert res.extracted_fields.amount == 1250000.0
    assert res.extracted_fields.issue_date == date(2026, 8, 15)
    assert res.extracted_fields.due_date == date(2026, 9, 30)
    assert res.extracted_fields.gstin == "27ABCDE1234F1Z5"
    assert res.extracted_fields.purchase_order_reference == "PO-SHAKTI-441"


def test_missing_optional_fields_produces_uncertainty():
    # Invoice without GSTIN or PO
    sample_text = """
    INVOICE # INV-NO-GSTIN-01
    From: Metro Fasteners
    Bill To: Delta Infrastructure
    Issue Date: 2026-08-10
    Due Date: 2026-10-10
    Invoice Total: 750,000
    """
    pdf_bytes = make_pdf(sample_text)
    res = parse_and_evaluate_pdf(pdf_bytes, filename="no_gstin.pdf")

    assert res.status == "SUCCESS"
    assert res.extracted_fields.extraction_confidence == ExtractionConfidence.MEDIUM
    assert "gstin" in res.extracted_fields.missing_fields
    assert "purchase_order_reference" in res.extracted_fields.missing_fields

    # Passed to existing verification engine -> PARTIALLY_VERIFIED
    assert res.evaluation is not None
    assert res.evaluation.verification.status == VerificationStatus.PARTIALLY_VERIFIED
    assert "GSTIN_MISSING" in res.evaluation.verification.reason_codes
    assert "PO_MISSING" in res.evaluation.verification.reason_codes
    assert any(f.label == "Verification uncertainty" for f in res.evaluation.risk.factors)


def test_missing_core_fields_low_confidence():
    # Incomplete text missing amount and dates
    sample_text = """
    Invoice ID: INV-PARTIAL-1
    Supplier: Unknown Corp
    """
    pdf_bytes = make_pdf(sample_text)
    res = parse_and_evaluate_pdf(pdf_bytes, filename="partial.pdf")

    assert res.status == "SUCCESS"
    assert res.extracted_fields.extraction_confidence == ExtractionConfidence.LOW
    assert "amount" in res.extracted_fields.missing_fields
    assert "buyer_name" in res.extracted_fields.missing_fields
    assert res.invoice is None
    assert res.evaluation is None


def test_empty_pdf_rejection():
    # Empty byte stream
    res = parse_and_evaluate_pdf(b"", filename="empty.pdf")
    assert res.status == "PDF_EMPTY"


def test_non_pdf_file_rejection():
    res = parse_and_evaluate_pdf(b"Not a real PDF file header", filename="text.txt")
    assert res.status == "PDF_INVALID"


def test_scanned_unreadable_pdf_rejection():
    # PDF with blank page (no text)
    doc = fitz.open()
    doc.new_page()  # blank page
    blank_bytes = doc.tobytes()
    doc.close()

    res = parse_and_evaluate_pdf(blank_bytes, filename="scanned.pdf")
    assert res.status == "PDF_TEXT_UNREADABLE"
    assert "OCR is not supported" in res.error_detail


def test_parse_invoice_endpoint_http():
    sample_text = """
    TAX INVOICE
    Invoice Number: INV-HTTP-101
    Supplier Name: Alpha Engineering
    Buyer Name: Beta Motors
    Invoice Date: 2026-08-20
    Due Date: 2026-10-20
    Total Amount: 1,500,000
    GSTIN: 27ABCDE1234F1Z5
    Purchase Order: PO-ALPHA-99
    """
    pdf_bytes = make_pdf(sample_text)

    # Valid upload
    resp = client.post(
        "/parse-invoice",
        files={"file": ("invoice.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SUCCESS"
    assert data["extracted_fields"]["invoice_number"] == "INV-HTTP-101"
    assert data["evaluation"]["verification"]["status"] == "VERIFIED"
    assert data["ledger_entry"]["source"] == "PDF_UPLOAD"

    # Non-PDF upload
    bad_resp = client.post(
        "/parse-invoice",
        files={"file": ("note.txt", b"plain text", "text/plain")},
    )
    assert bad_resp.status_code == 400
