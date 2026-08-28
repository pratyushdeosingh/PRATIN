"""Deterministic tests for the Capital Agent decision pipeline."""
import pytest

from backend.app.fixtures import providers, scenarios
from contracts.models import (
    MarketRequest,
    Provider,
    RiskAssessment,
    RiskBand,
    VerificationResult,
    VerificationStatus,
)
from services.capital_market.agent import analyze_provider, generate_market as analyze_all
from services.capital_market.engine import generate_market
from services.capital_market.market_data import MarketConditions, MarketRegime


def make_request(risk_score=24, provider_list=None, requirements=None, verification=None, risk=None, opportunity_id="OPP-1"):
    scenario = scenarios()["urgent"]
    verification = verification or VerificationResult(
        status=VerificationStatus.VERIFIED, confidence=.95, verified_fields=["all"],
        uncertain_fields=[], reasons=["ok"])
    risk = risk or RiskAssessment(
        score=risk_score,
        band=RiskBand.LOW if risk_score < 30 else RiskBand.MODERATE if risk_score < 55 else RiskBand.HIGH,
        confidence=.9, factors=[], missing_information=[])
    return MarketRequest(
        opportunity_id=opportunity_id,
        invoice=scenario.invoice,
        requirements=requirements or scenario.requirements,
        verification=verification,
        risk=risk,
        providers=provider_list or providers(),
    )


def offer_for(request, provider):
    return next(o for o in generate_market(request).offers if o.provider_id == provider.id)


# --- 1. Low-risk invoice produces an offer for an eligible provider ----------

def test_low_risk_invoice_produces_offer_for_eligible_provider():
    request = make_request(risk_score=24, provider_list=[providers()[1]])  # NBFC
    offer = generate_market(request).offers[0]
    assert offer.status == "OFFER"
    assert offer.financed_amount is not None and offer.financed_amount > 0
    assert offer.annual_rate is not None and offer.annual_rate > 0
    assert offer.advance_rate is not None and 0 < offer.advance_rate <= 1


# --- 2. Risk above appetite causes DECLINE ------------------------------------

def test_risk_above_appetite_causes_decline():
    bank = providers()[0]  # appetite 42
    request = make_request(risk_score=70, provider_list=[bank])
    offer = generate_market(request).offers[0]
    assert offer.status == "DECLINE"
    assert any("appetite" in r for r in offer.reasons)


# --- 3. Insufficient liquidity causes DECLINE ---------------------------------

def test_insufficient_liquidity_causes_decline():
    bank = providers()[0].model_copy(update={"available_liquidity": 100_000})
    request = make_request(provider_list=[bank])
    offer = generate_market(request).offers[0]
    assert offer.status == "DECLINE"
    assert any("liquidity" in r.lower() for r in offer.reasons)


# --- 4. Maximum ticket size is respected --------------------------------------

def test_maximum_ticket_size_is_respected():
    fund = providers()[3].model_copy(update={"max_ticket_size": 400_000})
    request = make_request(provider_list=[fund])
    offer = generate_market(request).offers[0]
    if offer.status == "OFFER":
        assert offer.financed_amount <= 400_000
    else:
        assert any("ticket" in r for r in offer.reasons)


# --- 5. Portfolio concentration is respected -----------------------------------

def test_portfolio_concentration_ceiling_blocks_offer():
    provider = providers()[1].model_copy(update={
        "current_exposure": 4_500_000,  # 75% of 6,000,000 capacity
        "portfolio_capacity": 6_000_000,
        "max_concentration_ratio": 0.72,
    })
    request = make_request(provider_list=[provider])
    offer = generate_market(request).offers[0]
    assert offer.status == "DECLINE"
    assert any("concentration" in r.lower() for r in offer.reasons)


def test_concentration_ratio_approaching_ceiling_raises_rate():
    base = analyze_provider(make_request(provider_list=[providers()[1]]), providers()[1])
    # Exposure at 55% of capacity (ceiling 72%): a 600k allocation keeps it
    # inside the ceiling but leaves less headroom than the base case.
    tight = providers()[1].model_copy(update={"current_exposure": 3_300_000})
    tight_analysis = analyze_provider(make_request(provider_list=[tight]), tight)
    assert tight_analysis.pricing.portfolio_adjustment > base.pricing.portfolio_adjustment
    assert tight_analysis.pricing.final_rate > base.pricing.final_rate


# --- 6. Preferred industries affect provider behaviour -------------------------

def test_preferred_industry_gets_more_attractive_terms():
    nbfc = providers()[1]  # prefers Manufacturing
    request = make_request(provider_list=[nbfc])
    preferred = generate_market(request).offers[0]
    # Change the invoice industry to a non-preferred one (same risk)
    other = scenarios()["urgent"].invoice.model_copy(update={"industry": "Chemicals"})
    request2 = make_request(provider_list=[nbfc])
    request2 = request2.model_copy(update={"invoice": other})
    non_preferred = generate_market(request2).offers[0]
    assert preferred.annual_rate < non_preferred.annual_rate
    assert preferred.advance_rate > non_preferred.advance_rate
    assert any("preferred industry" in r for r in preferred.reasons)


# --- 7. Different provider types generate different offers ---------------------

def test_different_provider_types_generate_different_offers():
    request = make_request()
    offers = [o for o in generate_market(request).offers if o.status == "OFFER"]
    signatures = {(o.provider_type, o.annual_rate, o.advance_rate, o.fees, o.settlement_hours) for o in offers}
    assert len(signatures) == len(offers) >= 2


# --- 8. Higher risk produces less favourable financing terms -------------------

def test_higher_risk_produces_less_favourable_terms():
    nbfc = providers()[1]
    low = analyze_provider(make_request(risk_score=20, provider_list=[nbfc]), nbfc)
    high = analyze_provider(make_request(risk_score=50, provider_list=[nbfc]), nbfc)
    assert high.pricing.final_rate > low.pricing.final_rate
    assert high.advance_rate < low.advance_rate


# --- 9. Market regime can affect pricing/behaviour ------------------------------

def test_market_regime_affects_pricing_and_advance():
    nbfc = providers()[1]
    request = make_request(provider_list=[nbfc])
    neutral = analyze_provider(request, nbfc, MarketConditions(regime=MarketRegime.NEUTRAL))
    stressed = analyze_provider(request, nbfc, MarketConditions(
        regime=MarketRegime.STRESSED, risk_premium_bps=1.0, advance_rate_adjustment=-0.04,
        tenor_adjustment_days=-10))
    # STRESSED regime tightens terms: lower advance, shorter tenor, and a
    # higher risk premium component in the rate decomposition.
    assert stressed.advance_rate < neutral.advance_rate
    assert stressed.tenor_days < neutral.tenor_days
    assert stressed.pricing.market_adjustment > neutral.pricing.market_adjustment
    # The shorter tenor reduces the tenor adjustment, which can offset the
    # market premium; the regime still materially changes the package.
    assert (stressed.pricing.risk_premium + stressed.pricing.market_adjustment
            > neutral.pricing.risk_premium + neutral.pricing.market_adjustment)


# --- 10. Provider liquidity affects allocation ----------------------------------

def test_provider_liquidity_affects_allocation():
    nbfc = providers()[1]
    request = make_request(provider_list=[nbfc])
    rich = nbfc.model_copy(update={"available_liquidity": 2_000_000})
    poor = nbfc.model_copy(update={"available_liquidity": 860_000})
    rich_analysis = analyze_provider(request, rich)
    poor_analysis = analyze_provider(request, poor)
    assert poor_analysis.financed_amount < rich_analysis.financed_amount
    assert poor_analysis.pricing.liquidity_adjustment > rich_analysis.pricing.liquidity_adjustment


# --- 11. Maximum total cost is respected when supplied --------------------------

def test_max_total_cost_ceiling_blocks_offer():
    fintech = providers()[2]  # high fee_rate 4% -> expensive
    requirements = scenarios()["urgent"].requirements.model_copy(update={"max_total_cost": 15_000})
    request = make_request(provider_list=[fintech], requirements=requirements)
    offer = generate_market(request).offers[0]
    assert offer.status == "DECLINE"
    assert any("cost" in r.lower() for r in offer.reasons)


def test_total_effective_cost_never_exceeds_supplied_ceiling():
    nbfc = providers()[1]
    requirements = scenarios()["urgent"].requirements.model_copy(update={"max_total_cost": 100_000})
    request = make_request(provider_list=[nbfc], requirements=requirements)
    offer = generate_market(request).offers[0]
    if offer.status == "OFFER":
        assert offer.total_effective_cost <= 100_000


# --- 12. Every decision contains useful reasons --------------------------------

def test_every_decision_contains_useful_reasons():
    request = make_request()
    for offer in generate_market(request).offers:
        assert offer.reasons, "offer/decline must carry reasons"
        for reason in offer.reasons:
            assert len(reason) >= 10


# --- 13. Same invoice + different provider state can produce different outcomes --

def test_same_invoice_different_provider_state_changes_outcome():
    # Two providers, identical risk appetite and ticket, but different liquidity.
    nbfc = providers()[1]
    rich = nbfc.model_copy(update={"id": "rich", "available_liquidity": 1_650_000})
    broke = nbfc.model_copy(update={"id": "broke", "available_liquidity": 50_000})
    request = make_request(provider_list=[rich, broke])
    offers = {o.provider_id: o for o in generate_market(request).offers}
    assert offers["rich"].status == "OFFER"
    assert offers["broke"].status == "DECLINE"


# --- 14. Existing API contract remains valid -----------------------------------

def test_existing_api_contract_remains_valid():
    from contracts.models import MarketResponse, Offer
    response = generate_market(make_request())
    assert isinstance(response, MarketResponse)
    assert all(isinstance(o, Offer) for o in response.offers)
    assert response.provenance == "SERVICE"


# --- 15. Existing deterministic behaviour does not regress ----------------------

def test_existing_deterministic_behaviour_does_not_regress():
    # Same input twice -> identical output
    request = make_request()
    first = generate_market(request)
    second = generate_market(request)
    assert first == second


# --- Extra: decline reasons name the hard constraint ----------------------------

def test_decline_reasons_name_the_hard_constraint():
    bank = providers()[0]  # ticket 700k < 800k min, settle 96h > 48h
    request = make_request(provider_list=[bank])
    offer = generate_market(request).offers[0]
    assert offer.status == "DECLINE"
    assert any("Maximum ticket" in r for r in offer.reasons)
    assert any("Settlement in" in r for r in offer.reasons)


# --- Extra: verification rejection blocks everyone ------------------------------

def test_verification_rejection_blocks_everyone():
    verification = VerificationResult(
        status=VerificationStatus.REJECTED, confidence=.9, verified_fields=[],
        uncertain_fields=[], reasons=["Invoice past due"])
    request = make_request(verification=verification)
    offers = generate_market(request).offers
    assert all(o.status == "DECLINE" for o in offers)
    assert all(any("verification" in r.lower() for r in o.reasons) for o in offers)


# --- Extra: partial financing below minimum declines ----------------------------

def test_partial_financing_below_minimum_declines():
    fund = providers()[3].model_copy(update={"max_ticket_size": 500_000})
    request = make_request(provider_list=[fund])
    offer = generate_market(request).offers[0]
    assert offer.status == "DECLINE"
    assert any("ticket" in r for r in offer.reasons)


# --- Extra: attractiveness is explainable ---------------------------------------

def test_attractiveness_assessment_is_explainable():
    nbfc = providers()[1]
    analysis = analyze_provider(make_request(provider_list=[nbfc]), nbfc)
    assert analysis.attractiveness is not None
    assert 0 <= analysis.attractiveness.score <= 100
    assert len(analysis.attractiveness.factors) >= 8
    assert all(f.explanation for f in analysis.attractiveness.factors)


# --- Extra: pricing decomposition is deterministic and explainable ---------------

def test_pricing_decomposition_is_deterministic_and_explainable():
    nbfc = providers()[1]
    a1 = analyze_provider(make_request(provider_list=[nbfc]), nbfc)
    a2 = analyze_provider(make_request(provider_list=[nbfc]), nbfc)
    assert a1.pricing == a2.pricing
    assert a1.pricing.final_rate == round(
        a1.pricing.base_return_rate + a1.pricing.risk_premium + a1.pricing.tenor_adjustment
        + a1.pricing.industry_adjustment + a1.pricing.liquidity_adjustment
        + a1.pricing.portfolio_adjustment + a1.pricing.market_adjustment, 2)
    assert len(a1.pricing.lines()) == 8


# --- Extra: expected return is positive and annualised --------------------------

def test_expected_return_is_positive_and_reasonable():
    nbfc = providers()[1]
    request = make_request(provider_list=[nbfc])
    offer = generate_market(request).offers[0]
    assert offer.expected_return > 0
    # Annualised return should exceed the interest-only component meaningfully
    # because fees amortise over the tenor.
    assert offer.expected_return > offer.annual_rate


# --- Extra: verify pipeline stages run in order via analyze_provider ------------

def test_analyze_provider_returns_full_internal_state():
    nbfc = providers()[1]
    analysis = analyze_provider(make_request(provider_list=[nbfc]), nbfc)
    assert analysis.hard.passed is True
    assert analysis.attractiveness is not None
    assert analysis.pricing is not None
    assert analysis.financed_amount is not None
    assert analysis.post_allocation_exposure_ratio is not None
    assert analysis.reasons
