"""Capital Market engine entrypoint.

Drives the Capital Agent (services.capital_market.agent) over every provider
in a MarketRequest and returns the strict MarketResponse contract. The public
signature is unchanged so existing in-process integrations keep working.
"""
from contracts.models import MarketRequest, MarketResponse, Offer

from .agent import act, analyze_provider, generate_market as _analyze
from .market_data import MarketConditions, load_market


def _build_offer(request: MarketRequest, analysis) -> Offer:
    """Build the strict Offer for one provider analysis."""
    return act(request, analysis)


def generate_market(request: MarketRequest) -> MarketResponse:
    """Evaluate the opportunity for every provider and return the offers."""
    market: MarketConditions = load_market()
    analyses = _analyze(request, market)
    offers: list[Offer] = [_build_offer(request, analysis) for analysis in analyses]
    return MarketResponse(offers=offers)
