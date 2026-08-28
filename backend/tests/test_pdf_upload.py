import os
os.environ["PRATIN_INTEGRATION_MODE"] = "fixture"
os.environ["PRATIN_DB_PATH"] = "data/test-pratin.db"

import fitz
from fastapi.testclient import TestClient
from backend.app.main import app, store

client = TestClient(app)


def setup_function():
    store.reset()


def make_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), text, fontsize=11)
    buf = doc.tobytes()
    doc.close()
    return buf


def test_backend_pdf_invoice_upload_and_ledger_integration():
    sample_text = """
    TAX INVOICE
    Invoice Number: INV-PDF-8888
    Supplier Name: Paramount Bearings
    Buyer Name: Mahindra Mobility
    Invoice Date: 2026-08-15
    Due Date: 2026-10-15
    Total Amount: 3,200,000.00
    GSTIN: 27ABCDE1234F1Z5
    Purchase Order: PO-2026-MAH-11
    """
    pdf_bytes = make_pdf(sample_text)

    # 1. Upload & Parse PDF
    resp = client.post(
        "/api/invoices/parse-pdf",
        files={"file": ("paramount_invoice.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SUCCESS"
    assert data["extracted_fields"]["invoice_number"] == "INV-PDF-8888"
    assert data["evaluation"]["verification"]["status"] == "VERIFIED"
    assert data["ledger_entry"]["source"] == "PDF_UPLOAD"
    assert data["ledger_entry"]["source_filename"] == "paramount_invoice.pdf"

    # 2. Risk Ledger query
    ledger = client.get("/api/risk-ledger").json()
    assert len(ledger) >= 1
    pdf_entry = next((e for e in ledger if e["invoice_number"] == "INV-PDF-8888"), None)
    assert pdf_entry is not None
    assert pdf_entry["amount"] == 3200000.0
    assert pdf_entry["verification"]["status"] == "VERIFIED"
    assert pdf_entry["risk"]["band"] in ["LOW", "MODERATE", "HIGH", "SEVERE"]

    # 3. Audit check
    audits = client.get("/api/audit").json()
    events = [a["event_type"] for a in audits]
    assert "PDF_INVOICE_PARSED" in events
    assert "RISK_EVALUATED" in events


def test_backend_pdf_invalid_file_rejected():
    bad_resp = client.post(
        "/api/invoices/parse-pdf",
        files={"file": ("invalid.txt", b"plain text", "text/plain")},
    )
    assert bad_resp.status_code == 400
