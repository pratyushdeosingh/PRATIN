"""Pure, deterministic counterfactual simulations over cloned marketplace state."""
from __future__ import annotations

from statistics import mean, median

from contracts.models import (FinancingRequirements, MarketRequest, MarketTwinOverrides,
    OpportunityRecord, Provider, RiskAssessment, StrategySimulationRequest)
from services.capital_market.agent import act, generate_market as analyze_market
from services.capital_market.market_data import MarketConditions, MarketRegime
from .matching import rank_offers


REGIMES = {
    "FAVORABLE": MarketConditions(MarketRegime.FAVORABLE, description="Synthetic favorable market.", advance_rate_adjustment=.01),
    "NEUTRAL": MarketConditions(MarketRegime.NEUTRAL),
    "CAUTIOUS": MarketConditions(MarketRegime.CAUTIOUS, description="Synthetic cautious market.", risk_premium_bps=.5, advance_rate_adjustment=-.02, tenor_adjustment_days=-5),
    "STRESSED": MarketConditions(MarketRegime.STRESSED, description="Synthetic stressed market.", risk_premium_bps=1, advance_rate_adjustment=-.04, tenor_adjustment_days=-10),
}


def _summary(decision, providers: list[Provider]) -> dict:
    ranked = decision.ranked_offers
    winner = next((x for x in ranked if x.offer.id == decision.recommended_offer_id), None)
    eligible = [x for x in ranked if x.eligible]
    offers = [x.offer for x in eligible if x.offer.annual_rate is not None]
    return {
        "winner_id": winner.offer.provider_id if winner else None,
        "winner_name": winner.offer.provider_name if winner else None,
        "winner_score": winner.suitability_score if winner else 0,
        "eligible_providers": len(eligible),
        "average_rate": round(mean(o.annual_rate for o in offers), 2) if offers else None,
        "capital_available": round(sum(p.available_liquidity for p in providers), 2),
        "ranked_offers": [x.model_dump(mode="json") for x in ranked],
    }


def _market(opportunity: OpportunityRecord, providers: list[Provider], requirements: FinancingRequirements,
            risk: RiskAssessment, regime: str = "NEUTRAL"):
    request = MarketRequest(opportunity_id=opportunity.id, invoice=opportunity.invoice, requirements=requirements,
        verification=opportunity.evaluation.verification, risk=risk, providers=providers)
    analyses = analyze_market(request, REGIMES[regime])
    offers = [act(request, analysis) for analysis in analyses]
    return rank_offers(opportunity.id, requirements, risk, offers,
        {provider.id: provider.available_liquidity for provider in providers})


def simulate(opportunity: OpportunityRecord, provider_state: list[Provider], overrides: MarketTwinOverrides) -> dict:
    if not opportunity.evaluation or not opportunity.match:
        raise ValueError("Run the opportunity through the market before simulating it")
    req_changes = {key: value for key, value in {
        "minimum_amount": overrides.minimum_amount,
        "max_settlement_hours": overrides.max_settlement_hours,
        "desired_tenor_days": overrides.desired_tenor_days,
        "max_total_cost": overrides.max_total_cost,
    }.items() if value is not None}
    requirements = opportunity.requirements.model_copy(update=req_changes)
    if requirements.minimum_amount > opportunity.invoice.amount:
        raise ValueError("Simulated minimum financing cannot exceed invoice amount")
    risk_score = overrides.risk_score if overrides.risk_score is not None else opportunity.evaluation.risk.score
    uncertainty_penalty = round((1 - opportunity.evaluation.risk.confidence) * 20, 1) if overrides.confidence_stress else 0
    adjusted_score = min(100, risk_score + uncertainty_penalty)
    risk = opportunity.evaluation.risk.model_copy(update={"score": adjusted_score})
    providers = []
    for provider in provider_state:
        if provider.id in overrides.removed_provider_ids:
            continue
        change = overrides.provider_overrides.get(provider.id)
        providers.append(provider.model_copy(update=change.model_dump(exclude_none=True) if change else {}))
    baseline = _summary(opportunity.match, provider_state)
    decision = _market(opportunity, providers, requirements, risk, overrides.market_regime or "NEUTRAL")
    simulated = _summary(decision, providers)
    base_by_id = {x["offer"]["provider_id"]: x for x in baseline["ranked_offers"]}
    changes = []
    for item in simulated["ranked_offers"]:
        before = base_by_id.get(item["offer"]["provider_id"])
        changes.append({"provider_id": item["offer"]["provider_id"], "provider_name": item["offer"]["provider_name"],
            "before_score": before["suitability_score"] if before else None, "after_score": item["suitability_score"],
            "before_eligible": before["eligible"] if before else False, "after_eligible": item["eligible"]})
    explanations = []
    for field, value in req_changes.items(): explanations.append(f"{field.replace('_', ' ')} changed from {getattr(opportunity.requirements, field)} to {value}.")
    if overrides.risk_score is not None: explanations.append(f"Risk score changed from {opportunity.evaluation.risk.score} to {overrides.risk_score}.")
    if overrides.market_regime: explanations.append(f"Synthetic market regime changed to {overrides.market_regime}.")
    if overrides.removed_provider_ids: explanations.append(f"Removed providers: {', '.join(overrides.removed_provider_ids)}.")
    if overrides.confidence_stress: explanations.append(f"Uncertainty penalty +{uncertainty_penalty}; stress-adjusted risk {adjusted_score}.")
    if baseline["winner_id"] != simulated["winner_id"]: explanations.append(f"Winner changed from {baseline['winner_name']} to {simulated['winner_name']}.")
    return {"baseline": baseline, "simulated": simulated, "winner_changed": baseline["winner_id"] != simulated["winner_id"],
        "previous_winner": baseline["winner_name"], "new_winner": simulated["winner_name"], "score_changes": changes,
        "provider_decision_changes": [x for x in changes if x["before_eligible"] != x["after_eligible"]],
        "explanations": explanations or ["No overrides supplied; simulation reproduces the canonical market."],
        "risk": {"raw": risk_score, "confidence": opportunity.evaluation.risk.confidence, "uncertainty_penalty": uncertainty_penalty, "adjusted": adjusted_score},
        "notice": "Pure deterministic simulation. No marketplace state was mutated."}


def counterfactual(opportunity: OpportunityRecord, providers: list[Provider], provider_id: str) -> dict:
    if not opportunity.match: raise ValueError("Run the market before requesting a counterfactual")
    ranked = next((x for x in opportunity.match.ranked_offers if x.offer.provider_id == provider_id), None)
    provider = next((x for x in providers if x.id == provider_id), None)
    if not ranked or not provider: raise LookupError("Provider was not part of this market")
    winner = next((x for x in opportunity.match.ranked_offers if x.offer.id == opportunity.match.recommended_offer_id), None)
    changes = []
    if provider.max_ticket_size < opportunity.requirements.minimum_amount: changes.append({"field":"max_ticket_size","current":provider.max_ticket_size,"required":opportunity.requirements.minimum_amount})
    if provider.settlement_hours > opportunity.requirements.max_settlement_hours: changes.append({"field":"settlement_hours","current":provider.settlement_hours,"required":opportunity.requirements.max_settlement_hours})
    if provider.available_liquidity < opportunity.requirements.minimum_amount: changes.append({"field":"available_liquidity","current":provider.available_liquidity,"required":opportunity.requirements.minimum_amount})
    disadvantages = []
    if ranked.eligible and winner:
        win_factors = {f.name: f.score * f.weight for f in winner.factors}
        for factor in ranked.factors:
            gap = round(win_factors.get(factor.name, 0) - factor.score * factor.weight, 1)
            if gap > 0: disadvantages.append({"factor":factor.name,"weighted_gap":gap})
        disadvantages.sort(key=lambda x: -x["weighted_gap"])
    return {"provider_id":provider_id,"provider_name":provider.name,"currently_eligible":ranked.eligible,
        "currently_winner": bool(winner and winner.offer.provider_id == provider_id), "hard_constraint_changes":changes,
        "ranking_disadvantages":disadvantages, "estimated_suitability":ranked.suitability_score,
        "explanation": "Eligibility changes are exact; ranking sensitivities are approximate and use canonical weighted factors."}


def strategy(opportunity: OpportunityRecord, providers: list[Provider], request: StrategySimulationRequest) -> dict:
    options = []
    for hours in [12, 24, 48, 72]:
        result = simulate(opportunity, providers, MarketTwinOverrides(minimum_amount=request.minimum_amount,
            max_settlement_hours=hours, desired_tenor_days=request.desired_tenor_days, max_total_cost=request.max_total_cost))
        options.append({"settlement_hours":hours, **{k:result["simulated"][k] for k in ["winner_name","winner_score","eligible_providers","average_rate","capital_available"]}})
    selected = simulate(opportunity, providers, MarketTwinOverrides(minimum_amount=request.minimum_amount,
        max_settlement_hours=request.max_settlement_hours, desired_tenor_days=request.desired_tenor_days, max_total_cost=request.max_total_cost))
    viable = [x for x in options if x["eligible_providers"]]
    recommendation = min(viable, key=lambda x: (x["average_rate"] or 999, x["settlement_hours"])) if viable else None
    return {"selected":selected, "trade_off_curve":options, "recommendation": recommendation,
        "recommendation_text": f"The {recommendation['settlement_hours']}h option gives the lowest average eligible rate in this deterministic comparison." if recommendation else "No tested deadline produced an eligible provider.",
        "notice":"Strategy simulation only; no persisted requirements changed."}


def intelligence(providers: list[Provider], opportunities: list[OpportunityRecord]) -> dict:
    total_capacity = sum(p.portfolio_capacity for p in providers); exposure = sum(p.current_exposure for p in providers)
    liquidity = sum(p.available_liquidity for p in providers); top = max((p.available_liquidity for p in providers), default=0)
    ranked = [r for o in opportunities if o.match for r in o.match.ranked_offers]
    eligible = [r for r in ranked if r.eligible]; rates = [r.offer.annual_rate for r in eligible if r.offer.annual_rate is not None]
    speeds = [r.offer.settlement_hours for r in eligible if r.offer.settlement_hours is not None]
    competition = round(100 * len(eligible) / max(len(ranked), 1), 1)
    health = "HEALTHY" if competition >= 60 and liquidity > exposure else "TIGHT" if competition >= 30 else "FRAGILE"
    return {"capital_utilization":round(100*exposure/max(total_capacity,1),1), "provider_concentration":round(100*max((p.current_exposure/p.portfolio_capacity for p in providers),default=0),1),
        "average_offered_rate":round(mean(rates),2) if rates else None, "median_settlement_hours":median(speeds) if speeds else None,
        "eligible_provider_ratio":competition, "top_provider_liquidity_share":round(100*top/max(liquidity,1),1),
        "competition_index":competition, "market_health":health, "notice":"Derived from current PRATIN marketplace state; explainable demo metrics."}


def stress_lab(opportunity: OpportunityRecord, providers: list[Provider]) -> dict:
    weakest = min(providers, key=lambda p: p.available_liquidity).id
    scenarios = {
        "LIQUIDITY CRUNCH": MarketTwinOverrides(provider_overrides={p.id:{"available_liquidity":round(p.available_liquidity*.6,2)} for p in providers}),
        "CREDIT SHOCK": MarketTwinOverrides(risk_score=min(100, opportunity.evaluation.risk.score+25)),
        "FAST-SETTLEMENT DEMAND": MarketTwinOverrides(max_settlement_hours=12),
        "PROVIDER FAILURE": MarketTwinOverrides(removed_provider_ids=[weakest]),
        "STRESSED MARKET": MarketTwinOverrides(market_regime="STRESSED"),
        "CONCENTRATION SHOCK": MarketTwinOverrides(provider_overrides={p.id:{"current_exposure":round(p.portfolio_capacity*p.max_concentration_ratio*.95,2)} for p in providers}),
    }
    results=[]
    for name, overrides in scenarios.items():
        outcome=simulate(opportunity,providers,overrides); summary=outcome["simulated"]
        failures=sum(not item["eligible"] for item in summary["ranked_offers"])
        results.append({"scenario":name,"winner":summary["winner_name"],"eligible_providers":summary["eligible_providers"],
            "average_rate":summary["average_rate"],"capital_available":summary["capital_available"],"failure_count":failures,
            "winner_changed":outcome["winner_changed"]})
    viability=mean(x["eligible_providers"]/max(len(providers),1) for x in results)
    stability=mean(0 if x["winner_changed"] else 1 for x in results)
    liquidity_ratio=mean(min(1,x["capital_available"]/max(sum(p.available_liquidity for p in providers),1)) for x in results)
    score=round(100*(.5*viability+.25*stability+.25*liquidity_ratio))
    return {"scenarios":results,"resilience_score":score,"factors":{"provider_viability":round(viability*100,1),
        "winner_stability":round(stability*100,1),"liquidity_retention":round(liquidity_ratio*100,1)},
        "notice":"Explainable demo resilience metric. Simulations do not mutate marketplace state."}
