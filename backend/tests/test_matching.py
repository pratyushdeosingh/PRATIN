from backend.app.matching import MATCHING_POLICY_VERSION, WEIGHTS, rank_offers
from contracts.models import FinancingRequirements, Offer, RiskAssessment, RiskBand

def offer(id,rate,amount,hours,cost): return Offer(id=id,opportunity_id="o",provider_id=id,provider_name=id,
    provider_type="BANK",status="OFFER",annual_rate=rate,advance_rate=amount/1_000_000,financed_amount=amount,
    fees=0,tenor_days=60,settlement_hours=hours,total_effective_cost=cost,expected_return=rate,reasons=[])

def test_lowest_rate_does_not_win_when_hard_constraints_fail():
    requirements=FinancingRequirements(minimum_amount=800_000,max_settlement_hours=48,desired_tenor_days=60)
    risk=RiskAssessment(score=24,band=RiskBand.LOW,confidence=.9,factors=[],missing_information=[])
    cheap=offer("cheap",9,700_000,96,10_000); fit=offer("fit",11,850_000,24,22_000)
    decision=rank_offers("o",requirements,risk,[cheap,fit],{"cheap":5_000_000,"fit":3_000_000})
    assert decision.recommended_offer_id == "fit"
    assert not next(x for x in decision.ranked_offers if x.offer.id=="cheap").eligible

def test_ranking_is_deterministic():
    requirements=FinancingRequirements(minimum_amount=800_000,max_settlement_hours=48,desired_tenor_days=60)
    risk=RiskAssessment(score=24,band=RiskBand.LOW,confidence=.9,factors=[],missing_information=[])
    offers=[offer("a",11,850_000,24,22_000),offer("b",12,900_000,2,58_000)]
    first=rank_offers("o",requirements,risk,offers,{"a":3_000_000,"b":2_000_000})
    second=rank_offers("o",requirements,risk,offers,{"a":3_000_000,"b":2_000_000})
    assert first == second

def test_hard_constraints_dominate_score_and_factors_use_canonical_weights():
    requirements=FinancingRequirements(minimum_amount=800_000,max_settlement_hours=48,desired_tenor_days=60)
    risk=RiskAssessment(score=24,band=RiskBand.LOW,confidence=.9,factors=[],missing_information=[])
    too_small=offer("small",7,799_999,2,1_000)
    eligible=offer("eligible",14,800_000,48,50_000)
    decision=rank_offers("o",requirements,risk,[too_small,eligible],{"small":9_000_000,"eligible":1_000_000})
    assert decision.recommended_offer_id == "eligible"
    assert decision.policy_version == MATCHING_POLICY_VERSION
    assert sum(WEIGHTS.values()) == 1
    winner=next(item for item in decision.ranked_offers if item.offer.id == "eligible")
    assert {factor.name.lower().replace(" ", "_"): factor.weight for factor in winner.factors} == WEIGHTS
