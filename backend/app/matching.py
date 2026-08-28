"""Hard constraints followed by the canonical explainable matching policy."""
from math import isclose
from typing import Literal

from contracts.models import (
    FinancingRequirements,
    MatchDecision,
    Offer,
    RankedOffer,
    RiskAssessment,
    ScoreFactor,
)

MATCHING_POLICY_VERSION = "matching-policy-1.2-smart-match"

PRIORITY_WEIGHTS: dict[str, dict[str, float]] = {
    "BALANCED": {
        "capital": 0.28,
        "cost": 0.32,
        "speed": 0.16,
        "tenor": 0.08,
        "risk_return": 0.08,
        "liquidity": 0.08,
    },
    "FASTEST": {
        "speed": 0.70,
        "capital": 0.10,
        "cost": 0.05,
        "tenor": 0.05,
        "risk_return": 0.05,
        "liquidity": 0.05,
    },
    "LOWEST_FEE": {
        "cost": 0.70,
        "capital": 0.10,
        "speed": 0.05,
        "tenor": 0.05,
        "risk_return": 0.05,
        "liquidity": 0.05,
    },
    "HIGHEST_ADVANCE": {
        "capital": 0.70,
        "cost": 0.10,
        "speed": 0.05,
        "tenor": 0.05,
        "risk_return": 0.05,
        "liquidity": 0.05,
    },
}

# Export canonical weights for backward compatibility
WEIGHTS = PRIORITY_WEIGHTS["BALANCED"]

for priority_name, weights_dict in PRIORITY_WEIGHTS.items():
    if not isclose(sum(weights_dict.values()), 1.0):
        raise RuntimeError(f"Matching policy weights for {priority_name} must sum to 1.0")


def rank_offers(
    opportunity_id: str,
    requirements: FinancingRequirements,
    risk: RiskAssessment,
    offers: list[Offer],
    liquidity: dict[str, float],
) -> MatchDecision:
    ranked: list[RankedOffer] = []
    offered_costs = [
        o.total_effective_cost
        for o in offers
        if o.status == "OFFER" and o.total_effective_cost is not None
    ]
    maximum_cost = max(offered_costs, default=1)

    active_priority = getattr(requirements, "priority", "BALANCED") or "BALANCED"
    active_weights = PRIORITY_WEIGHTS.get(active_priority, PRIORITY_WEIGHTS["BALANCED"])

    for offer in offers:
        failures: list[str] = []
        factors: list[ScoreFactor] = []
        if offer.status == "DECLINE":
            failures.extend(offer.reasons)
        else:
            if (offer.financed_amount or 0) < requirements.minimum_amount:
                failures.append(
                    f"Offers ₹{offer.financed_amount:,.0f}, below required ₹{requirements.minimum_amount:,.0f}."
                )
            if (offer.settlement_hours or 10**6) > requirements.max_settlement_hours:
                failures.append(
                    f"Settlement takes {offer.settlement_hours}h, beyond the {requirements.max_settlement_hours}h limit."
                )
            if requirements.max_total_cost and (offer.total_effective_cost or 0) > requirements.max_total_cost:
                failures.append("Total effective cost exceeds the supplier ceiling.")

            if active_priority == "HIGHEST_ADVANCE":
                capital = min(100.0, max(0.0, (offer.advance_rate or 0) * 100.0))
            else:
                capital = min(
                    100,
                    70 + 30 * ((offer.financed_amount or 0) - requirements.minimum_amount) / max(requirements.minimum_amount, 1),
                )
            cost = 100 * (1 - (offer.total_effective_cost or maximum_cost) / (maximum_cost * 1.15))
            speed = 100 * (1 - min(1, (offer.settlement_hours or 720) / max(requirements.max_settlement_hours, 1)))
            tenor = max(0, 100 - abs((offer.tenor_days or 0) - requirements.desired_tenor_days) * 2)
            risk_return = min(100, 55 + (offer.expected_return or 0) - risk.score / 3)
            liquid = min(100, 100 * liquidity.get(offer.provider_id, 0) / max((offer.financed_amount or 1) * 3, 1))
            values = {
                "capital": capital,
                "cost": max(0, cost),
                "speed": speed,
                "tenor": tenor,
                "risk_return": risk_return,
                "liquidity": liquid,
            }
            explanations = {
                "capital": f"Advances ₹{offer.financed_amount:,.0f} against the supplier's ₹{requirements.minimum_amount:,.0f} floor.",
                "cost": f"Total effective cost is ₹{offer.total_effective_cost:,.0f}, including fees and tenor-adjusted interest.",
                "speed": f"Settlement is available in {offer.settlement_hours} hours.",
                "tenor": f"Offer tenor is {offer.tenor_days} days versus {requirements.desired_tenor_days} requested.",
                "risk_return": f"Balances risk score {risk.score:.0f} with provider expected annualised return {offer.expected_return:.1f}%.",
                "liquidity": f"Provider has ₹{liquidity.get(offer.provider_id, 0):,.0f} available before allocation.",
            }
            factors = [
                ScoreFactor(
                    name=k.replace("_", " ").title(),
                    score=round(max(0, min(100, v)), 1),
                    weight=active_weights[k],
                    explanation=explanations[k],
                )
                for k, v in values.items()
            ]
        score = 0 if failures else round(sum(f.score * f.weight for f in factors), 1)
        ranked.append(
            RankedOffer(
                offer=offer,
                eligible=not failures,
                suitability_score=score,
                factors=factors,
                hard_constraint_failures=failures,
            )
        )

    ranked.sort(key=lambda item: (-int(item.eligible), -item.suitability_score, item.offer.id))
    eligible = [item for item in ranked if item.eligible]
    for index, item in enumerate(eligible, 1):
        item.rank = index
    winner = eligible[0] if eligible else None

    reasons: list[str] = []
    tradeoffs: list[str] = []

    if winner:
        reasons.append(
            f"Meets your {requirements.max_settlement_hours}h funding requirement (settlement in {winner.offer.settlement_hours}h)."
        )
        reasons.append(
            f"Can provide approximately ₹{(winner.offer.financed_amount or 0):,.0f} against requested ₹{requirements.minimum_amount:,.0f}."
        )
        reasons.append(
            f"Estimated financing fee: approximately ₹{(winner.offer.fees or 0):,.0f} (Total effective cost: ₹{(winner.offer.total_effective_cost or 0):,.0f} at {winner.offer.annual_rate:.2f}% annual rate)."
        )
        reasons.append(
            f"Selected under {active_priority.replace('_', ' ').title()} priority with top suitability score {winner.suitability_score:.1f}/100."
        )
        reasons.append(
            f"Invoice risk is {risk.band.value} ({risk.score:.1f}/100)."
        )

        # Trade-off analysis against alternatives
        for alt in eligible[1:]:
            if alt.offer.advance_rate and winner.offer.advance_rate and alt.offer.advance_rate > winner.offer.advance_rate:
                tradeoffs.append(
                    f"{alt.offer.provider_name} offers a higher advance rate ({alt.offer.advance_rate*100:.0f}% vs {winner.offer.advance_rate*100:.0f}%), but has higher cost (₹{alt.offer.total_effective_cost:,.0f}) or slower settlement ({alt.offer.settlement_hours}h)."
                )
            elif alt.offer.settlement_hours and winner.offer.settlement_hours and alt.offer.settlement_hours < winner.offer.settlement_hours:
                tradeoffs.append(
                    f"{alt.offer.provider_name} settles faster ({alt.offer.settlement_hours}h vs {winner.offer.settlement_hours}h), but provides lower advance or higher fees."
                )
            elif alt.offer.total_effective_cost and winner.offer.total_effective_cost and alt.offer.total_effective_cost < winner.offer.total_effective_cost:
                tradeoffs.append(
                    f"{alt.offer.provider_name} offers lower total effective cost (₹{alt.offer.total_effective_cost:,.0f}), but requires slower settlement ({alt.offer.settlement_hours}h)."
                )
    else:
        reasons = ["No provider offer satisfies every supplier hard constraint."]
        for item in ranked:
            if item.hard_constraint_failures:
                tradeoffs.append(f"{item.offer.provider_name}: " + " • ".join(item.hard_constraint_failures))

    return MatchDecision(
        opportunity_id=opportunity_id,
        recommended_offer_id=winner.offer.id if winner else None,
        ranked_offers=ranked,
        recommendation_reasons=reasons,
        tradeoffs=tradeoffs,
        priority=active_priority,
        policy_version=MATCHING_POLICY_VERSION,
    )
