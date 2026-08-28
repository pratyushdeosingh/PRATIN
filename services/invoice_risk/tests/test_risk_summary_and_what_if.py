from datetime import date, timedelta
import pytest
from contracts.models import (
    Invoice,
    RiskBand,
    RiskDecisionSummary,
    RiskSimulationRequest,
    RiskSimulationResult,
    VerificationResult,
    VerificationStatus,
)
from services.invoice_risk.engine import (
    assess_risk,
    create_risk_ledger_entry,
    evaluate,
    generate_risk_summary,
    get_standard_what_if_scenarios,
    simulate_risk_change,
    verify_invoice,
)


@pytest.fixture
def clean_invoice():
    today = date.today()
    return Invoice(
        invoice_number="INV-WHATIF-001",
        supplier_name="Apex Precision Engineering Pvt Ltd",
        buyer_name="Zenith Automotive Ltd",
        amount=500000.0,
        currency="INR",
        issue_date=today - timedelta(days=10),
        due_date=today + timedelta(days=45),
        gstin="27AABCA1234C1Z5",
        supplier_state="Maharashtra",
        purchase_order_reference="PO-2026-99",
        subtotal=450000.0,
        tax_amount=50000.0,
        buyer_rating=0.85,
        supplier_history_months=36,
        on_time_payment_ratio=0.92,
        prior_defaults=0,
    )


def test_positive_and_negative_factor_extraction(clean_invoice):
    verification = verify_invoice(clean_invoice)
    assessment = assess_risk(clean_invoice, verification)
    assert assessment.summary is not None
    summary = assessment.summary

    # Reducers: buyer reliability, payment history, supplier history
    assert len(summary.top_risk_reducers) >= 2
    for r in summary.top_risk_reducers:
        assert r.points < 0

    # Risk contributors: maturity
    for c in summary.top_risk_contributors:
        assert c.points > 0

    # Sorted order
    for i in range(len(summary.top_risk_reducers) - 1):
        assert summary.top_risk_reducers[i].points <= summary.top_risk_reducers[i + 1].points

    for i in range(len(summary.top_risk_contributors) - 1):
        assert summary.top_risk_contributors[i].points >= summary.top_risk_contributors[i + 1].points


def test_generated_summary_low_risk(clean_invoice):
    verification = verify_invoice(clean_invoice)
    assessment = assess_risk(clean_invoice, verification)
    assert assessment.band == RiskBand.LOW
    assert assessment.summary is not None
    assert "LOW risk" in assessment.summary.human_readable_explanation
    assert len(assessment.summary.primary_drivers) >= 2
    assert any("buyer" in d.lower() for d in assessment.summary.primary_drivers)


def test_generated_summary_high_risk(clean_invoice):
    risky_invoice = clean_invoice.model_copy(update={
        "buyer_rating": 0.20,
        "on_time_payment_ratio": 0.40,
        "supplier_history_months": 2,
        "prior_defaults": 2,
        "amount": 12000000.0,
    })
    verification = verify_invoice(risky_invoice)
    assessment = assess_risk(risky_invoice, verification)
    assert assessment.band in (RiskBand.HIGH, RiskBand.SEVERE)
    assert assessment.summary is not None
    assert assessment.band.value in assessment.summary.human_readable_explanation
    assert len(assessment.summary.top_risk_contributors) >= 3


def test_duplicate_what_if_adds_exactly_35_points(clean_invoice):
    verification = verify_invoice(clean_invoice)
    original = assess_risk(clean_invoice, verification)
    assert original.score < 30  # LOW

    result = simulate_risk_change(
        clean_invoice,
        verification,
        RiskSimulationRequest(simulate_duplicate=True),
    )
    assert result.score_delta == 35.0
    assert result.simulated_score == round(original.score + 35.0, 1)
    assert result.simulated_band == RiskBand.MODERATE
    assert "35 points" in result.explanation


def test_payment_history_what_if_brackets(clean_invoice):
    verification = verify_invoice(clean_invoice)
    
    # Simulate critical payment delinquency (40%)
    res_critical = simulate_risk_change(
        clean_invoice,
        verification,
        RiskSimulationRequest(simulated_on_time_payment_ratio=0.40),
    )
    # Original payment history points was -10.0 (for 0.92 ratio), new is +20.0 (for <0.50 ratio), delta = +30.0
    assert res_critical.score_delta == 30.0

    # Simulate exceptional payment history (98%)
    res_exceptional = simulate_risk_change(
        clean_invoice,
        verification,
        RiskSimulationRequest(simulated_on_time_payment_ratio=0.98),
    )
    # Original -10.0, new -15.0, delta = -5.0
    assert res_exceptional.score_delta == -5.0


def test_maturity_what_if_brackets(clean_invoice):
    verification = verify_invoice(clean_invoice)
    
    # Urgent maturity (10 days) -> +8.0 pts
    res_urgent = simulate_risk_change(
        clean_invoice,
        verification,
        RiskSimulationRequest(simulated_days_until_due=10),
    )
    # Original was 45 days (+2.0 pts). Difference: +8.0 - 2.0 = +6.0
    assert res_urgent.score_delta == 6.0

    # Long maturity (>60 days) -> 0.0 pts
    res_long = simulate_risk_change(
        clean_invoice,
        verification,
        RiskSimulationRequest(simulated_days_until_due=90),
    )
    assert res_long.score_delta == -2.0


def test_amount_what_if_concentration_brackets(clean_invoice):
    verification = verify_invoice(clean_invoice)
    # Original amount 500k (<1M) -> 0.0 pts
    
    # 5M -> +8.0 pts
    res_5m = simulate_risk_change(
        clean_invoice,
        verification,
        RiskSimulationRequest(simulated_amount=5000000.0),
    )
    assert res_5m.score_delta == 8.0

    # 12M -> +12.0 pts
    res_12m = simulate_risk_change(
        clean_invoice,
        verification,
        RiskSimulationRequest(simulated_amount=12000000.0),
    )
    assert res_12m.score_delta == 12.0


def test_verification_uncertainty_what_if(clean_invoice):
    verification = verify_invoice(clean_invoice)
    assert verification.status == VerificationStatus.VERIFIED
    
    res = simulate_risk_change(
        clean_invoice,
        verification,
        RiskSimulationRequest(simulated_verification_status=VerificationStatus.PARTIALLY_VERIFIED),
    )
    assert res.score_delta == 12.0


def test_score_clamping_to_zero_and_hundred(clean_invoice):
    verification = verify_invoice(clean_invoice)
    
    # Extreme risk triggers
    res_max = simulate_risk_change(
        clean_invoice,
        verification,
        RiskSimulationRequest(
            simulate_duplicate=True,  # +35
            simulated_on_time_payment_ratio=0.10,  # +20 (vs -10: +30)
            simulated_amount=15000000.0,  # +12
            simulated_prior_defaults=5,  # +30
            simulated_buyer_rating=0.0,  # 0 (vs -15.3: +15.3)
            simulated_verification_status=VerificationStatus.REJECTED,  # +45
        ),
    )
    assert res_max.simulated_score == 100.0
    assert res_max.simulated_band == RiskBand.SEVERE

    # Ultra clean
    res_min = simulate_risk_change(
        clean_invoice,
        verification,
        RiskSimulationRequest(
            simulated_buyer_rating=1.0,  # -18.0
            simulated_on_time_payment_ratio=1.0,  # -15.0
            simulated_supplier_history_months=60,  # -8.0
            simulated_days_until_due=100,  # 0.0
            simulated_amount=100000.0,  # 0.0
        ),
    )
    # Base 38 - 18 - 15 - 8 = -3 -> clamped to 0.0
    assert res_min.simulated_score == 0.0
    assert res_min.simulated_band == RiskBand.LOW


def test_simulation_does_not_mutate_invoice_or_ledger(clean_invoice):
    entry = create_risk_ledger_entry(clean_invoice)
    orig_amount = clean_invoice.amount
    orig_score = entry.risk.score

    res = simulate_risk_change(
        clean_invoice,
        entry.verification,
        RiskSimulationRequest(simulated_amount=10000000.0, simulate_duplicate=True),
    )
    assert res.simulated_score != orig_score
    assert clean_invoice.amount == orig_amount
    assert entry.risk.score == orig_score
    assert entry.amount == orig_amount


def test_standard_what_if_scenarios_generation(clean_invoice):
    verification = verify_invoice(clean_invoice)
    scenarios = get_standard_what_if_scenarios(clean_invoice, verification)
    assert len(scenarios) >= 4
    names = [s.scenario_name for s in scenarios]
    assert any("Duplicate" in n for n in names)
    assert any("Payment" in n for n in names)
    assert any("Amount" in n for n in names)
    assert any("Maturity" in n for n in names)
