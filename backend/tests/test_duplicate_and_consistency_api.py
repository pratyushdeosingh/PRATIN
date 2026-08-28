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
    page.insert_text((40, 60), text, fontsize=10)
    buf = doc.tobytes()
    doc.close()
    return buf


def test_duplicate_pdf_upload_persists_in_ledger_with_high_risk():
    pdf_text = """
    TAX INVOICE
    Invoice Number: INV-DUP-TEST-001
    Supplier Name: Paramount Bearings
    Buyer Name: Mahindra Mobility
    Invoice Date: 2026-08-15
    Due Date: 2026-10-15
    Total Amount: 3,200,000.00
    GSTIN: 27ABCDE1234F1Z5
    Purchase Order: PO-2026-MAH-11
    """
    pdf_bytes = make_pdf(pdf_text)

    # 1. Upload first time
    r1 = client.post("/api/invoices/parse-pdf", files={"file": ("invoice_v1.pdf", pdf_bytes, "application/pdf")})
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["evaluation"]["verification"]["duplicate_check"]["duplicate_detected"] is False

    # 2. Upload second time (exact duplicate)
    r2 = client.post("/api/invoices/parse-pdf", files={"file": ("invoice_v2.pdf", pdf_bytes, "application/pdf")})
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["evaluation"]["verification"]["duplicate_check"]["duplicate_detected"] is True
    assert "DUPLICATE_INVOICE" in d2["evaluation"]["verification"]["reason_codes"]
    assert any(f["label"] == "Duplicate invoice" for f in d2["evaluation"]["risk"]["factors"])

    # 3. Check Risk Ledger contains the duplicate entry
    ledger = client.get("/api/risk-ledger").json()
    assert len(ledger) >= 2
    dup_entry = ledger[0]  # latest
    assert dup_entry["verification"]["duplicate_check"]["duplicate_detected"] is True
    assert dup_entry["verification"]["duplicate_check"]["matched_invoice_number"] == "INV-DUP-TEST-001"
