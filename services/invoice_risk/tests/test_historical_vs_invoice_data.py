from datetime import date, timedelta
import pytest
from contracts.models import (
    CounterpartyHistoricalProfile,
    Invoice,
    RiskBand,
    RiskFactorSource,
    RiskSimulationRequest,
    VerificationStatus,
)
from services.invoice_risk.engine import (
    KNOWN_COUNTERPARTY_PROFILES,
    assess_risk,
    evaluate,
    resolve_counterparty_profile,
    simulate_risk_change,
    verify_invoice,
)
from services.invoice_risk.pdf_parser import parse_and_evaluate_pdf
from services.invoice_risk.tests.test_pdf_parser import make_pdf


def test_invoice_derived_fields_come_from_pdf_invoice():
    text = """
    TAX INVOICE
    Invoice Number: INV-DOC-777
    Supplier Name: Alpha Tech Labs
    Buyer Name: Beta Retailers
    Issue Date: 2026-08-01
    Due Date: 2026-09-15
    Total Amount: INR 1,500,000.00
    GSTIN: 27AABCA1234F1Z5
    Purchase Order: PO-888999
    Subtotal: 1,500,000.00
    Tax Amount: 0.00
    """
    pdf_bytes = make_pdf(text)
    res = parse_and_evaluate_pdf(pdf_bytes, filename="inv_doc.pdf")
    assert res.status == "SUCCESS"
    assert res.invoice is not None
    assert res.invoice.invoice_number == "INV-DOC-777"
    assert res.invoice.supplier_name == "Alpha Tech Labs"
    assert res.invoice.buyer_name == "Beta Retailers"
    assert res.invoice.amount == 1500000.0
    assert res.invoice.due_date == date(2026, 9, 15)

    # Risk assessment should have factors categorized correctly
    assert res.evaluation is not None
    factors = res.evaluation.risk.factors
    large_ticket_factor = next(f for f in factors if f.label == "Large ticket")
    assert large_ticket_factor.source_category == RiskFactorSource.INVOICE_DERIVED
    assert "extracted from invoice" in large_ticket_factor.explanation.lower()

    maturity_factor = next(f for f in factors if f.label == "Invoice maturity")
    assert maturity_factor.source_category == RiskFactorSource.INVOICE_DERIVED


def test_historical_factors_come_from_profile_data_not_current_invoice():
    inv = Invoice(
        invoice_number="INV-REG-101",
        supplier_name="Shakti Components",
        buyer_name="Orion Auto Systems",
        amount=500000.0,
        issue_date=date.today() - timedelta(days=5),
        due_date=date.today() + timedelta(days=35),
    )
    eval_res = evaluate(inv)
    factors = eval_res.risk.factors

    # Check buyer reliability factor
    buyer_f = next(f for f in factors if f.label == "Buyer reliability")
    assert buyer_f.source_category == RiskFactorSource.HISTORICAL_COUNTERPARTY
    assert "based on historical counterparty data" in buyer_f.explanation
    assert buyer_f.points < 0  # Points reduced due to good reliability

    # Check payment history factor
    pmt_f = next(f for f in factors if f.label == "Payment history")
    assert pmt_f.source_category == RiskFactorSource.HISTORICAL_COUNTERPARTY
    assert "based on historical payment records" in pmt_f.explanation

    # Check supplier operating history factor
    sup_f = next(f for f in factors if f.label == "Supplier operating history")
    assert sup_f.source_category == RiskFactorSource.HISTORICAL_COUNTERPARTY
    assert "based on supplier profile data" in sup_f.explanation


def test_missing_historical_data_represented_as_unknown_unavailable():
    # An unlisted supplier and buyer with no historical records
    inv = Invoice(
        invoice_number="INV-UNKNOWN-001",
        supplier_name="Completely Brand New Supplier Pvt Ltd",
        buyer_name="Unknown Unlisted Buyer Corp",
        amount=300000.0,
        issue_date=date.today() - timedelta(days=2),
        due_date=date.today() + timedelta(days=40),
        buyer_rating=None,
        on_time_payment_ratio=None,
        supplier_history_months=None,
        prior_defaults=None,
    )
    eval_res = evaluate(inv, existing_invoices=[])
    factors = eval_res.risk.factors

    buyer_f = next(f for f in factors if f.label == "Buyer reliability")
    assert buyer_f.points == 0.0
    assert buyer_f.reason_code == "BUYER_RELIABILITY_UNKNOWN"
    assert "unavailable" in buyer_f.explanation.lower()
    assert buyer_f.source_category == RiskFactorSource.HISTORICAL_COUNTERPARTY

    pmt_f = next(f for f in factors if f.label == "Payment history")
    assert pmt_f.points == 0.0
    assert pmt_f.reason_code == "PAYMENT_HISTORY_UNKNOWN"
    assert "unavailable" in pmt_f.explanation.lower()
    assert pmt_f.source_category == RiskFactorSource.HISTORICAL_COUNTERPARTY

    sup_f = next(f for f in factors if f.label == "Supplier operating history")
    assert sup_f.points == 0.0
    assert sup_f.reason_code == "SUPPLIER_MATURITY_UNKNOWN"
    assert "unavailable" in sup_f.explanation.lower()
    assert sup_f.source_category == RiskFactorSource.HISTORICAL_COUNTERPARTY

    assert "buyer_historical_rating" in eval_res.risk.missing_information
    assert "buyer_payment_history" in eval_res.risk.missing_information
    assert "supplier_operating_history" in eval_res.risk.missing_information


def test_store_derived_historical_data_calculation():
    # Create past invoices stored for a buyer and supplier
    past_invoices = [
        Invoice(
            invoice_number="INV-PAST-1",
            supplier_name="Delta Tooling",
            buyer_name="Mega Auto Works",
            amount=400000.0,
            buyer_rating=0.80,
            on_time_payment_ratio=0.90,
            supplier_history_months=30,
            prior_defaults=0,
        ),
        Invoice(
            invoice_number="INV-PAST-2",
            supplier_name="Delta Tooling",
            buyer_name="Mega Auto Works",
            amount=600000.0,
            buyer_rating=0.84,
            on_time_payment_ratio=0.94,
            supplier_history_months=32,
            prior_defaults=0,
        ),
    ]

    new_inv = Invoice(
        invoice_number="INV-NEW-3",
        supplier_name="Delta Tooling",
        buyer_name="Mega Auto Works",
        amount=500000.0,
        issue_date=date.today() - timedelta(days=1),
        due_date=date.today() + timedelta(days=45),
    )

    profile = resolve_counterparty_profile(new_inv, existing_invoices=past_invoices)
    assert profile.source == "STORE_DERIVED"
    assert profile.buyer_rating == 0.82  # (0.80 + 0.84) / 2
    assert profile.on_time_payment_ratio == 0.92  # (0.90 + 0.94) / 2
    assert profile.supplier_history_months == 32  # max(30, 32)
    assert "Calculated from 2 buyer" in profile.provenance_detail


def test_explicit_profile_scoring_and_explainability():
    inv = Invoice(
        invoice_number="INV-EXP-1",
        supplier_name="Custom Supplier",
        buyer_name="Custom Buyer",
        amount=400000.0,
        issue_date=date.today() - timedelta(days=2),
        due_date=date.today() + timedelta(days=50),
        buyer_rating=0.90,
        on_time_payment_ratio=0.95,
        supplier_history_months=36,
        prior_defaults=0,
    )
    eval_res = evaluate(inv)
    assert eval_res.risk.band == RiskBand.LOW
    assert eval_res.risk.score < 30

    # Summary explanation reflects historical fundamentals
    assert eval_res.risk.summary is not None
    assert "LOW risk" in eval_res.risk.summary.human_readable_explanation


def test_what_if_simulation_retains_source_categories():
    inv = Invoice(
        invoice_number="INV-SIM-1",
        supplier_name="Shakti Components",
        buyer_name="Orion Auto Systems",
        amount=500000.0,
        issue_date=date.today() - timedelta(days=2),
        due_date=date.today() + timedelta(days=45),
    )
    ver = verify_invoice(inv)
    sim_req = RiskSimulationRequest(
        scenario_name="Lower Payment History",
        simulated_on_time_payment_ratio=0.60,
    )
    sim_res = simulate_risk_change(inv, ver, sim_req)
    assert sim_res.score_delta > 0  # Risk increased
    mod_f = next(f for f in sim_res.modified_factors if f.label == "Payment history")
    assert mod_f.source_category == RiskFactorSource.HISTORICAL_COUNTERPARTY
    assert "60%" in mod_f.explanation
