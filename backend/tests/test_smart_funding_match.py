"""Deterministic tests for Smart Funding Match and User-Requirement-Based Offer Recommendation."""
from datetime import date, timedelta
import pytest
from contracts.models import (
    FinancingRequirements,
    Invoice,
    MatchDecision,
    Offer,
    OpportunityCreate,
    Provider,
    RankedOffer,
    RiskAssessment,
    RiskBand,
    VerificationResult,
    VerificationStatus,
    MarketRequest,
)
from backend.app.matching import MATCHING_POLICY_VERSION, PRIORITY_WEIGHTS, WEIGHTS, rank_offers
from services.capital_market.agent import analyze_provider, act
from services.capital_market.market_data import load_market


def make_offer(
    provider_id: str,
    provider_name: str,
    status: str = "OFFER",
    annual_rate: float = 10.0,
    advance_rate: float = 0.85,
    financed_amount: float = 850_000,
    fees: float = 8_000,
    settlement_hours: int = 24,
    total_effective_cost: float = 25_000,
    expected_return: float = 9.5,
    reasons: list[str] | None = None,
) -> Offer:
    return Offer(
        id=f"off-{provider_id}",
        opportunity_id="OPP-TEST-1",
        provider_id=provider_id,
        provider_name=provider_name,
        provider_type="BANK" if "Bank" in provider_name else "NBFC" if "NBFC" in provider_name else "FINTECH",
        status=status,  # type: ignore
        annual_rate=annual_rate if status == "OFFER" else None,
        advance_rate=advance_rate if status == "OFFER" else None,
        financed_amount=financed_amount if status == "OFFER" else None,
        fees=fees if status == "OFFER" else None,
        tenor_days=60 if status == "OFFER" else None,
        settlement_hours=settlement_hours if status == "OFFER" else None,
        total_effective_cost=total_effective_cost if status == "OFFER" else None,
        expected_return=expected_return if status == "OFFER" else None,
        reasons=reasons or [],
    )


def test_fastest_priority_selects_faster_eligible_provider():
    # Provider A: 24h, 85% advance, fee 8k, cost 22k
    # Provider B: 2h, 80% advance, fee 30k, cost 45k
    prov_a = make_offer("prov-a", "VegaFlow NBFC", settlement_hours=24, advance_rate=0.85, financed_amount=850_000, total_effective_cost=22_000)
    prov_b = make_offer("prov-b", "PulseTrade Capital", settlement_hours=2, advance_rate=0.80, financed_amount=800_000, total_effective_cost=45_000)
    
    risk = RiskAssessment(score=25, band=RiskBand.LOW, confidence=0.95, factors=[], missing_information=[])
    reqs = FinancingRequirements(
        minimum_amount=800_000,
        max_settlement_hours=48,
        desired_tenor_days=60,
        priority="FASTEST",
    )
    liquidity = {"prov-a": 3_000_000, "prov-b": 3_000_000}
    decision = rank_offers("OPP-TEST-1", reqs, risk, [prov_a, prov_b], liquidity)

    assert decision.recommended_offer_id == "off-prov-b"
    assert "Fastest" in decision.recommendation_reasons[3]


def test_lowest_fee_priority_selects_lower_cost_provider():
    # Provider A: 24h, 85% advance, cost 15k
    # Provider B: 2h, 92% advance, cost 55k
    prov_a = make_offer("prov-a", "Astra Commercial Bank", settlement_hours=24, advance_rate=0.85, financed_amount=850_000, total_effective_cost=15_000)
    prov_b = make_offer("prov-b", "PulseTrade Capital", settlement_hours=2, advance_rate=0.92, financed_amount=920_000, total_effective_cost=55_000)
    
    risk = RiskAssessment(score=25, band=RiskBand.LOW, confidence=0.95, factors=[], missing_information=[])
    reqs = FinancingRequirements(
        minimum_amount=800_000,
        max_settlement_hours=48,
        desired_tenor_days=60,
        priority="LOWEST_FEE",
    )
    liquidity = {"prov-a": 3_000_000, "prov-b": 3_000_000}
    decision = rank_offers("OPP-TEST-1", reqs, risk, [prov_a, prov_b], liquidity)

    assert decision.recommended_offer_id == "off-prov-a"
    assert "Lowest Fee" in decision.recommendation_reasons[3]


def test_highest_advance_priority_selects_higher_advance_provider():
    # Provider A: 24h, 80% advance (800k), cost 20k
    # Provider B: 48h, 95% advance (950k), cost 35k
    prov_a = make_offer("prov-a", "VegaFlow NBFC", settlement_hours=24, advance_rate=0.80, financed_amount=800_000, total_effective_cost=20_000)
    prov_b = make_offer("prov-b", "PulseTrade Capital", settlement_hours=48, advance_rate=0.95, financed_amount=950_000, total_effective_cost=35_000)
    
    risk = RiskAssessment(score=25, band=RiskBand.LOW, confidence=0.95, factors=[], missing_information=[])
    reqs = FinancingRequirements(
        minimum_amount=800_000,
        max_settlement_hours=48,
        desired_tenor_days=60,
        priority="HIGHEST_ADVANCE",
    )
    liquidity = {"prov-a": 3_000_000, "prov-b": 3_000_000}
    decision = rank_offers("OPP-TEST-1", reqs, risk, [prov_a, prov_b], liquidity)

    assert decision.recommended_offer_id == "off-prov-b"
    assert "Highest Advance" in decision.recommendation_reasons[3]


def test_balanced_priority_produces_deterministic_ranking():
    prov_a = make_offer("prov-a", "VegaFlow NBFC", settlement_hours=24, advance_rate=0.85, financed_amount=850_000, total_effective_cost=22_000)
    prov_b = make_offer("prov-b", "PulseTrade Capital", settlement_hours=2, advance_rate=0.92, financed_amount=920_000, total_effective_cost=45_000)
    
    risk = RiskAssessment(score=25, band=RiskBand.LOW, confidence=0.95, factors=[], missing_information=[])
    reqs = FinancingRequirements(
        minimum_amount=800_000,
        max_settlement_hours=48,
        desired_tenor_days=60,
        priority="BALANCED",
    )
    liquidity = {"prov-a": 3_000_000, "prov-b": 3_000_000}
    d1 = rank_offers("OPP-TEST-1", reqs, risk, [prov_a, prov_b], liquidity)
    d2 = rank_offers("OPP-TEST-1", reqs, risk, [prov_a, prov_b], liquidity)
    assert d1 == d2


def test_changing_user_requirements_changes_recommendation():
    # Same two offers
    prov_speed = make_offer("prov-speed", "PulseTrade Capital", settlement_hours=2, advance_rate=0.80, financed_amount=800_000, total_effective_cost=50_000)
    prov_cheap = make_offer("prov-cheap", "Astra Commercial Bank", settlement_hours=48, advance_rate=0.90, financed_amount=900_000, total_effective_cost=15_000)
    
    risk = RiskAssessment(score=25, band=RiskBand.LOW, confidence=0.95, factors=[], missing_information=[])
    liquidity = {"prov-speed": 3_000_000, "prov-cheap": 3_000_000}

    # Case 1: Priority = FASTEST -> prov-speed wins
    reqs_speed = FinancingRequirements(minimum_amount=800_000, max_settlement_hours=48, desired_tenor_days=60, priority="FASTEST")
    dec_speed = rank_offers("OPP-TEST-1", reqs_speed, risk, [prov_speed, prov_cheap], liquidity)
    assert dec_speed.recommended_offer_id == "off-prov-speed"

    # Case 2: Priority = LOWEST_FEE -> prov-cheap wins
    reqs_cheap = FinancingRequirements(minimum_amount=800_000, max_settlement_hours=48, desired_tenor_days=60, priority="LOWEST_FEE")
    dec_cheap = rank_offers("OPP-TEST-1", reqs_cheap, risk, [prov_speed, prov_cheap], liquidity)
    assert dec_cheap.recommended_offer_id == "off-prov-cheap"


def test_provider_exceeding_settlement_deadline_is_excluded():
    # Provider takes 96 hours, user requires <= 48 hours
    slow_prov = make_offer("slow", "Astra Bank", settlement_hours=96, advance_rate=0.90, financed_amount=900_000, total_effective_cost=10_000)
    fast_prov = make_offer("fast", "VegaFlow NBFC", settlement_hours=24, advance_rate=0.85, financed_amount=850_000, total_effective_cost=25_000)
    
    risk = RiskAssessment(score=25, band=RiskBand.LOW, confidence=0.95, factors=[], missing_information=[])
    reqs = FinancingRequirements(minimum_amount=800_000, max_settlement_hours=48, desired_tenor_days=60)
    liquidity = {"slow": 5_000_000, "fast": 2_000_000}
    decision = rank_offers("OPP-TEST-1", reqs, risk, [slow_prov, fast_prov], liquidity)

    assert decision.recommended_offer_id == "off-fast"
    slow_ranked = next(r for r in decision.ranked_offers if r.offer.id == "off-slow")
    assert not slow_ranked.eligible
    assert any("beyond the 48h limit" in f for f in slow_ranked.hard_constraint_failures)


def test_no_provider_satisfies_requirements_returns_closest_alternatives():
    # User requires 950k, but both providers offer less
    prov_a = make_offer("prov-a", "Astra Bank", settlement_hours=96, advance_rate=0.70, financed_amount=700_000)
    prov_b = make_offer("prov-b", "VegaFlow NBFC", settlement_hours=24, advance_rate=0.85, financed_amount=850_000)
    
    risk = RiskAssessment(score=25, band=RiskBand.LOW, confidence=0.95, factors=[], missing_information=[])
    reqs = FinancingRequirements(minimum_amount=950_000, max_settlement_hours=48, desired_tenor_days=60)
    liquidity = {"prov-a": 5_000_000, "prov-b": 2_000_000}
    decision = rank_offers("OPP-TEST-1", reqs, risk, [prov_a, prov_b], liquidity)

    assert decision.recommended_offer_id is None
    assert "No provider offer satisfies every supplier hard constraint" in decision.recommendation_reasons[0]
    assert len(decision.tradeoffs) > 0
    assert any("below required ₹950,000" in t for t in decision.tradeoffs)


def test_provider_hard_gates_ticket_size_and_risk_appetite():
    provider = Provider(
        id="bank-test",
        name="Conservative Bank",
        provider_type="BANK",
        available_liquidity=5_000_000,
        risk_appetite=30,  # low risk appetite
        min_return_rate=8.0,
        max_ticket_size=500_000,  # ticket cap 500k
        preferred_industries=["Manufacturing"],
        settlement_hours=48,
        max_concentration_ratio=0.5,
        current_exposure=100_000,
        portfolio_capacity=5_000_000,
        base_advance_rate=0.80,
        fee_rate=0.005,
    )
    
    # 1. Invoice amount exceeds max ticket size (1M > 500k)
    inv_large = Invoice(
        invoice_number="INV-LARGE",
        supplier_name="Apex Precision",
        buyer_name="Zenith Motors",
        amount=1_000_000,
        currency="INR",
        industry="Manufacturing",
    )
    verif = VerificationResult(status=VerificationStatus.VERIFIED, confidence=0.95, verified_fields=[], uncertain_fields=[], reasons=[])
    risk_low = RiskAssessment(score=20, band=RiskBand.LOW, confidence=0.95, factors=[], missing_information=[])
    # 1. Requested financing exceeds provider maximum ticket size (600k > 500k)
    reqs1 = FinancingRequirements(minimum_amount=600_000, max_settlement_hours=72, desired_tenor_days=60)
    req1 = MarketRequest(
        opportunity_id="OPP-1",
        invoice=inv_large,
        requirements=reqs1,
        verification=verif,
        risk=risk_low,
        providers=[provider],
    )
    analysis1 = analyze_provider(req1, provider, load_market())
    offer1 = act(req1, analysis1)
    # Provider ticket capacity is a supplier-side mandate mismatch. The
    # provider prices its available ticket and Core's matcher makes it ineligible.
    assert offer1.status == "OFFER"
    decision1 = rank_offers(req1.opportunity_id, reqs1, risk_low, [offer1], {provider.id: provider.available_liquidity})
    assert decision1.ranked_offers[0].eligible is False
    assert any("below required" in reason.lower() for reason in decision1.ranked_offers[0].hard_constraint_failures)

    # 2. High-risk invoice exceeds provider risk appetite (risk 65 > appetite 30)
    inv_small = Invoice(
        invoice_number="INV-SMALL",
        supplier_name="Apex Precision",
        buyer_name="Zenith Motors",
        amount=400_000,
        currency="INR",
        industry="Manufacturing",
    )
    reqs2 = FinancingRequirements(minimum_amount=300_000, max_settlement_hours=72, desired_tenor_days=60)
    risk_high = RiskAssessment(score=65, band=RiskBand.HIGH, confidence=0.95, factors=[], missing_information=[])
    req2 = MarketRequest(
        opportunity_id="OPP-2",
        invoice=inv_small,
        requirements=reqs2,
        verification=verif,
        risk=risk_high,
        providers=[provider],
    )
    analysis2 = analyze_provider(req2, provider, load_market())
    offer2 = act(req2, analysis2)
    assert offer2.status == "DECLINE"
    assert any("exceeds the provider appetite" in r.lower() for r in offer2.reasons)
