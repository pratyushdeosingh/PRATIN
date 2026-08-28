"""Invoice persistence tests: parser output survives backend restarts."""
import os
import sys

os.environ["PRATIN_INTEGRATION_MODE"] = "fixture"
os.environ["PRATIN_DB_PATH"] = "data/test-invoice-persistence.db"

import fitz
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app, store
from backend.app.storage import Store
from contracts.models import Invoice, PersistedInvoice

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


def test_parse_pdf_persists_invoice_record():
    sample = """
    TAX INVOICE
    Invoice Number: INV-PERSIST-001
    Supplier Name: Bharat Forgings
    Buyer Name: Tata Auto Systems
    Invoice Date: 2026-08-10
    Due Date: 2026-10-10
    Total Amount: 2,800,000.00
    GSTIN: 27ABCDE1234F1Z5
    Purchase Order: PO-TATA-22
    """
    resp = client.post("/api/invoices/parse-pdf",
                       files={"file": ("bharat_invoice.pdf", make_pdf(sample), "application/pdf")})
    assert resp.status_code == 200
    data = resp.json()
    assert data["persisted_invoice"] is not None
    record = data["persisted_invoice"]
    assert record["invoice_number"] == "INV-PERSIST-001"
    assert record["supplier_name"] == "Bharat Forgings"
    assert record["buyer_name"] == "Tata Auto Systems"
    assert record["amount"] == 2800000.0
    assert record["status"] == "PARSED"
    assert record["created_at"]
    assert record["updated_at"]


def test_reparsing_same_invoice_updates_not_duplicates():
    sample = """
    TAX INVOICE
    Invoice Number: INV-PERSIST-002
    Supplier Name: Apex Castings
    Buyer Name: Zenon Auto
    Invoice Date: 2026-08-01
    Due Date: 2026-09-30
    Total Amount: 1,500,000.00
    """
    pdf = make_pdf(sample)
    first = client.post("/api/invoices/parse-pdf",
                        files={"file": ("apex.pdf", pdf, "application/pdf")}).json()
    second = client.post("/api/invoices/parse-pdf",
                         files={"file": ("apex.pdf", pdf, "application/pdf")}).json()
    assert first["persisted_invoice"]["id"] == second["persisted_invoice"]["id"]
    assert len(client.get("/api/invoices").json()) == 1


def test_invoices_survive_store_restart(tmp_path, monkeypatch):
    sample = """
    TAX INVOICE
    Invoice Number: INV-PERSIST-003
    Supplier Name: Persist Corp
    Buyer Name: Retain Ltd
    Invoice Date: 2026-08-02
    Due Date: 2026-09-28
    Total Amount: 900,000.00
    """
    client.post("/api/invoices/parse-pdf",
                files={"file": ("persist.pdf", make_pdf(sample), "application/pdf")})

    # A fresh Store instance against the SAME sqlite file must see the record.
    fresh = Store(store.path)
    try:
        records = fresh.invoices()
        assert any(r.invoice_number == "INV-PERSIST-003" for r in records)
    finally:
        fresh.close() if hasattr(fresh, "close") else None


def test_get_persisted_invoice_endpoint():
    sample = """
    TAX INVOICE
    Invoice Number: INV-PERSIST-004
    Supplier Name: Query Co
    Buyer Name: Fetch Ltd
    Invoice Date: 2026-08-03
    Due Date: 2026-09-25
    Total Amount: 1,200,000.00
    """
    client.post("/api/invoices/parse-pdf",
                files={"file": ("query.pdf", make_pdf(sample), "application/pdf")})
    resp = client.get("/api/invoices/INV-PERSIST-004")
    assert resp.status_code == 200
    assert resp.json()["supplier_name"] == "Query Co"

    missing = client.get("/api/invoices/INV-DOES-NOT-EXIST")
    assert missing.status_code == 404


def test_sqlite_store_save_get_upsert_direct():
    invoice = Invoice(
        invoice_number="INV-DIRECT-1",
        supplier_name="Direct Supplier",
        buyer_name="Direct Buyer",
        amount=1_000_000,
        industry="Manufacturing",
    )
    record = store.save_invoice(invoice)
    assert isinstance(record, PersistedInvoice)
    assert record.id.startswith("INV-")
    assert store.get_invoice("INV-DIRECT-1").id == record.id
    assert any(r.invoice_number == "INV-DIRECT-1" for r in store.invoices())

    updated = invoice.model_copy(update={"amount": 1_100_000})
    record2 = store.save_invoice(updated)
    assert record2.id == record.id
    assert record2.amount == 1_100_000
    assert len([r for r in store.invoices() if r.invoice_number == "INV-DIRECT-1"]) == 1
