from backend.app.fixtures import providers, scenarios
from contracts.models import InvoiceEvaluation, MarketRequest, RiskAssessment, RiskBand, VerificationResult, VerificationStatus
from services.capital_market.engine import generate_market

def request(risk_score=24, provider_list=None):
    scenario=scenarios()["urgent"]
    verification=VerificationResult(status=VerificationStatus.VERIFIED,confidence=.95,verified_fields=["all"],uncertain_fields=[],reasons=["ok"])
    risk=RiskAssessment(score=risk_score,band=RiskBand.LOW if risk_score<30 else RiskBand.HIGH,confidence=.9,factors=[],missing_information=[])
    return MarketRequest(opportunity_id="OPP-1",invoice=scenario.invoice,requirements=scenario.requirements,
        verification=verification,risk=risk,providers=provider_list or providers())

def test_provider_offers_are_meaningfully_different():
    offers=[x for x in generate_market(request()).offers if x.status=="OFFER"]
    assert len({(x.annual_rate,x.advance_rate,x.fees,x.settlement_hours) for x in offers}) == len(offers)

def test_low_risk_bank_declines_high_risk_opportunity():
    bank=providers()[0]
    offer=generate_market(request(70,[bank])).offers[0]
    assert offer.status == "DECLINE" and "appetite" in offer.reasons[0]

def test_insufficient_liquidity_prevents_offer():
    bank=providers()[0].model_copy(update={"available_liquidity":100_000,"max_ticket_size":1_000_000})
    assert generate_market(request(24,[bank])).offers[0].status == "DECLINE"

