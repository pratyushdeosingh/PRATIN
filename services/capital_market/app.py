from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from contracts.models import MarketRequest, MarketResponse
from .agent import analyze_provider
from .engine import generate_market

app = FastAPI(title="PRATIN Capital Market Agents", version="1.1.0")

# Local demo cockpit is served from :5173 and calls the agents directly.
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"])

@app.get("/")
def root():
    """Service overview so a bare browser visit is not a 404."""
    return {
        "service": "PRATIN Capital Market Agents",
        "status": "ok",
        "description": "Autonomous capital-provider agents that evaluate financing "
                       "opportunities and return explainable offers or declines.",
        "endpoints": {
            "health": "/health",
            "offers": "/offers",
            "analysis": "/analysis",
            "docs": "/docs",
        },
        "notice": "Synthetic demo engine. No real underwriting, credit approval, "
                  "financial advice or fund movement occurs.",
    }

@app.get("/health")
def health(): return {"status": "ok", "service": "capital-market", "version": "1.1.0"}

@app.post("/offers", response_model=MarketResponse)
def offers(request: MarketRequest): return generate_market(request)


class AgentAnalysisResponse(BaseModel):
    """Secondary, scoped view of the Capital Agent's internal reasoning.

    Not part of the canonical MarketRequest -> MarketResponse contract; used
    by the cockpit's Capital Agents tab for a richer explainable view.
    """
    offers: list[dict]


@app.post("/analysis", response_model=AgentAnalysisResponse)
def analysis(request: MarketRequest) -> AgentAnalysisResponse:
    """Full agent stack per provider: hard gates, attractiveness, pricing."""
    analyses = [analyze_provider(request, provider) for provider in request.providers]
    return AgentAnalysisResponse(offers=[_serialize(a) for a in analyses])


def _serialize(a) -> dict:
    """Serialize the internal ProviderAnalysis into plain JSON for the tab."""
    hard = {"passed": a.hard.passed, "failures": a.hard.failures}
    attractiveness = None
    if a.attractiveness is not None:
        attractiveness = {
            "score": a.attractiveness.score,
            "factors": [{"label": f.label, "score": f.score, "explanation": f.explanation}
                        for f in a.attractiveness.factors],
        }
    pricing = None
    if a.pricing is not None:
        pricing = {
            "base_return_rate": a.pricing.base_return_rate,
            "risk_premium": a.pricing.risk_premium,
            "tenor_adjustment": a.pricing.tenor_adjustment,
            "industry_adjustment": a.pricing.industry_adjustment,
            "liquidity_adjustment": a.pricing.liquidity_adjustment,
            "portfolio_adjustment": a.pricing.portfolio_adjustment,
            "market_adjustment": a.pricing.market_adjustment,
            "final_rate": a.pricing.final_rate,
            "lines": a.pricing.lines(),
        }
    offer = {
        "provider_id": a.provider.id,
        "provider_name": a.provider.name,
        "provider_type": a.provider.provider_type,
        "status": "OFFER" if a.hard.passed else "DECLINE",
        "advance_rate": a.advance_rate,
        "financed_amount": a.financed_amount,
        "tenor_days": a.tenor_days,
        "fees": a.fees,
        "total_effective_cost": a.total_effective_cost,
        "expected_return": a.expected_return,
        "settlement_hours": a.settlement_hours,
        "reasons": a.reasons,
        "post_allocation_exposure_ratio": a.post_allocation_exposure_ratio,
    }
    return {
        "provider": {
            "id": a.provider.id,
            "name": a.provider.name,
            "provider_type": a.provider.provider_type,
            "available_liquidity": a.provider.available_liquidity,
            "risk_appetite": a.provider.risk_appetite,
            "min_return_rate": a.provider.min_return_rate,
            "max_ticket_size": a.provider.max_ticket_size,
            "preferred_industries": a.provider.preferred_industries,
            "settlement_hours": a.provider.settlement_hours,
            "max_concentration_ratio": a.provider.max_concentration_ratio,
            "current_exposure": a.provider.current_exposure,
            "portfolio_capacity": a.provider.portfolio_capacity,
            "base_advance_rate": a.provider.base_advance_rate,
            "fee_rate": a.provider.fee_rate,
        },
        "hard": hard,
        "attractiveness": attractiveness,
        "pricing": pricing,
        "offer": offer,
        "market": {
            "regime": a.market.regime,
            "source": a.market.source,
            "description": a.market.description,
        },
    }
