"""Hard constraints followed by an explainable multi-objective score."""
from contracts.models import FinancingRequirements, MatchDecision, Offer, RankedOffer, RiskAssessment, ScoreFactor

WEIGHTS = {"capital": .28, "cost": .32, "speed": .16, "tenor": .08, "risk_return": .08, "liquidity": .08}

def rank_offers(opportunity_id: str, requirements: FinancingRequirements, risk: RiskAssessment,
                offers: list[Offer], liquidity: dict[str, float]) -> MatchDecision:
    ranked: list[RankedOffer] = []
    offered_costs = [o.total_effective_cost for o in offers if o.status == "OFFER" and o.total_effective_cost is not None]
    maximum_cost = max(offered_costs, default=1)
    for offer in offers:
        failures: list[str] = []
        factors: list[ScoreFactor] = []
        if offer.status == "DECLINE": failures.extend(offer.reasons)
        else:
            if (offer.financed_amount or 0) < requirements.minimum_amount:
                failures.append(f"Offers ₹{offer.financed_amount:,.0f}, below required ₹{requirements.minimum_amount:,.0f}.")
            if (offer.settlement_hours or 10**6) > requirements.max_settlement_hours:
                failures.append(f"Settlement takes {offer.settlement_hours}h, beyond the {requirements.max_settlement_hours}h limit.")
            if requirements.max_total_cost and (offer.total_effective_cost or 0) > requirements.max_total_cost:
                failures.append("Total effective cost exceeds the supplier ceiling.")
            capital = min(100, 70 + 30 * ((offer.financed_amount or 0) - requirements.minimum_amount) / max(requirements.minimum_amount, 1))
            cost = 100 * (1 - (offer.total_effective_cost or maximum_cost) / (maximum_cost * 1.15))
            speed = 100 * (1 - min(1, (offer.settlement_hours or 720) / max(requirements.max_settlement_hours, 1)))
            tenor = max(0, 100 - abs((offer.tenor_days or 0) - requirements.desired_tenor_days) * 2)
            risk_return = min(100, 55 + (offer.expected_return or 0) - risk.score / 3)
            liquid = min(100, 100 * liquidity.get(offer.provider_id, 0) / max((offer.financed_amount or 1) * 3, 1))
            values = {"capital": capital, "cost": max(0, cost), "speed": speed, "tenor": tenor,
                      "risk_return": risk_return, "liquidity": liquid}
            explanations = {
                "capital": f"Advances ₹{offer.financed_amount:,.0f} against the supplier's ₹{requirements.minimum_amount:,.0f} floor.",
                "cost": f"Total effective cost is ₹{offer.total_effective_cost:,.0f}, including fees and tenor-adjusted interest.",
                "speed": f"Settlement is available in {offer.settlement_hours} hours.",
                "tenor": f"Offer tenor is {offer.tenor_days} days versus {requirements.desired_tenor_days} requested.",
                "risk_return": f"Balances risk score {risk.score:.0f} with provider expected annualised return {offer.expected_return:.1f}%.",
                "liquidity": f"Provider has ₹{liquidity.get(offer.provider_id, 0):,.0f} available before allocation.",
            }
            factors = [ScoreFactor(name=k.replace("_", " ").title(), score=round(max(0, min(100, v)), 1),
                                   weight=WEIGHTS[k], explanation=explanations[k]) for k, v in values.items()]
        score = 0 if failures else round(sum(f.score * f.weight for f in factors), 1)
        ranked.append(RankedOffer(offer=offer, eligible=not failures, suitability_score=score, factors=factors,
                                  hard_constraint_failures=failures))
    ranked.sort(key=lambda item: (-int(item.eligible), -item.suitability_score, item.offer.id))
    eligible = [item for item in ranked if item.eligible]
    for index, item in enumerate(eligible, 1): item.rank = index
    winner = eligible[0] if eligible else None
    reasons = [] if not winner else [
        f"{winner.offer.provider_name} satisfies every supplier hard constraint.",
        f"It leads the weighted two-sided suitability policy at {winner.suitability_score:.1f}/100.",
        "The recommendation balances usable capital, effective cost, speed, tenor, provider return and remaining liquidity.",
    ]
    return MatchDecision(opportunity_id=opportunity_id, recommended_offer_id=winner.offer.id if winner else None,
                         ranked_offers=ranked, recommendation_reasons=reasons or ["No provider offer satisfies every hard constraint."])
