"""State-aware deterministic capital-provider agents."""
from hashlib import sha256

from contracts.models import MarketRequest, MarketResponse, Offer, RiskBand, VerificationStatus


def _id(opportunity_id: str, provider_id: str) -> str:
    return "OFF-" + sha256(f"{opportunity_id}|{provider_id}".encode()).hexdigest()[:10].upper()


def generate_market(request: MarketRequest) -> MarketResponse:
    offers: list[Offer] = []
    for provider in request.providers:
        reasons: list[str] = []
        decline = None
        if request.verification.status == VerificationStatus.REJECTED:
            decline = "Invoice verification was rejected."
        elif request.risk.score > provider.risk_appetite:
            decline = f"Risk score {request.risk.score:.0f} exceeds appetite {provider.risk_appetite:.0f}."
        elif provider.available_liquidity < min(request.requirements.minimum_amount, provider.max_ticket_size):
            decline = "Available liquidity cannot support the required ticket."
        elif provider.current_exposure / provider.portfolio_capacity >= provider.max_concentration_ratio:
            decline = "Portfolio concentration ceiling has been reached."
        if decline:
            offers.append(Offer(id=_id(request.opportunity_id, provider.id), opportunity_id=request.opportunity_id,
                provider_id=provider.id, provider_name=provider.name, provider_type=provider.provider_type,
                status="DECLINE", reasons=[decline]))
            continue
        industry_fit = request.invoice.industry.lower() in {x.lower() for x in provider.preferred_industries}
        advance_rate = provider.base_advance_rate + (.02 if industry_fit else -.03)
        advance_rate -= max(0, request.risk.score - 30) / 1000
        advance_rate = round(max(.55, min(.94, advance_rate)), 3)
        financed = round(min(request.invoice.amount * advance_rate, provider.max_ticket_size, provider.available_liquidity), 2)
        risk_premium = request.risk.score * (.055 if provider.provider_type == "BANK" else .07) / 10
        annual_rate = round(provider.min_return_rate + risk_premium + (0 if industry_fit else .65), 2)
        tenor = request.requirements.desired_tenor_days
        fees = round(financed * provider.fee_rate, 2)
        interest = round(financed * annual_rate / 100 * tenor / 365, 2)
        total_cost = round(interest + fees, 2)
        expected_return = round((total_cost / financed) * (365 / tenor) * 100, 2)
        reasons.extend([
            f"Risk score {request.risk.score:.0f} is inside appetite {provider.risk_appetite:.0f}.",
            "Preferred-sector pricing applied." if industry_fit else "Non-preferred-sector pricing premium applied.",
            f"₹{provider.available_liquidity:,.0f} liquidity is available before allocation.",
        ])
        offers.append(Offer(id=_id(request.opportunity_id, provider.id), opportunity_id=request.opportunity_id,
            provider_id=provider.id, provider_name=provider.name, provider_type=provider.provider_type,
            status="OFFER", annual_rate=annual_rate, advance_rate=advance_rate, financed_amount=financed,
            fees=fees, tenor_days=tenor, settlement_hours=provider.settlement_hours,
            total_effective_cost=total_cost, expected_return=expected_return, reasons=reasons))
    return MarketResponse(offers=offers)

