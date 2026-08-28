from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from contracts.models import MarketRequest, MarketResponse
from .agent import analyze_provider
from .engine import generate_market
from .intelligence import build_intelligence
from .research import (
    FirecrawlClient,
    ResearchError,
    run_research,
    _load_telemetry,
    _save_telemetry,
)
from .trace import ExecutionTrace

app = FastAPI(title="PRATIN Capital Market Agents", version="1.2.0")

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
            "research": "/research",
            "docs": "/docs",
        },
        "notice": "Synthetic demo engine. No real underwriting, credit approval, "
                  "financial advice or fund movement occurs.",
    }


@app.get("/health")
def health(): return {"status": "ok", "service": "capital-market", "version": "1.2.0"}


@app.post("/offers", response_model=MarketResponse)
def offers(request: MarketRequest): return generate_market(request)


class AgentAnalysisResponse(BaseModel):
    """Secondary, scoped view of the Capital Agent's internal reasoning.

    Not part of the canonical MarketRequest -> MarketResponse contract; used
    by the cockpit's Capital Agents tab for a richer explainable view.
    """
    offers: list[dict]
    research: dict | None = None
    trace: dict | None = None


@app.post("/analysis", response_model=AgentAnalysisResponse)
def analysis(request: MarketRequest, refresh: bool = Query(False)) -> AgentAnalysisResponse:
    """Full agent stack per provider with live researched intelligence.

    The research pass runs exactly once per opportunity context (cached
    afterwards). ``refresh=true`` forces a fresh Firecrawl pass.
    """
    trace = ExecutionTrace()
    trace.start("observe_invoice")
    trace.done("observe_invoice", f"Invoice {request.invoice.invoice_number} "
                                  f"₹{request.invoice.amount:,.0f} • {request.invoice.industry}")

    trace.start("load_risk")
    trace.done("load_risk", f"Risk {request.risk.score}/100 ({request.risk.band.value})")

    try:
        trace.start("search_market")
        outcome = run_research(request.invoice, request.requirements, refresh=refresh, on_step=None)
        if outcome.status == "cached":
            trace.skip("search_market", "Provider intelligence served from cache")
            trace.skip("select_providers", "Cached providers reused")
            trace.skip("research_providers", "No pages scraped — cache hit")
            trace.skip("extract_terms", "Facts served from cache")
        elif outcome.status == "live":
            trace.done("search_market", f"{outcome.telemetry.searches} search used")
            trace.done("select_providers", f"{len(outcome.providers)} providers selected")
            trace.done("research_providers", f"{outcome.telemetry.pages_scraped} official pages scraped")
            trace.done("extract_terms", "Financing terms extracted")
        else:
            trace.fail("search_market", outcome.error or "Research unavailable")
            trace.skip("select_providers", "Skipped — research unavailable")
            trace.skip("research_providers", "Skipped — research unavailable")
            trace.skip("extract_terms", "Skipped — research unavailable")
    except ResearchError as exc:
        trace.fail("search_market", str(exc))

    report = build_intelligence(outcome, request.invoice, request.requirements) \
        if outcome.providers else None

    if report and report.providers:
        trace.done("score_providers",
                   ", ".join(f"{p['provider']['provider_name']} {p['score']['total']:.0f}/100"
                             for p in report.providers))
        trace.done("evaluate_suitability",
                   ", ".join(f"{p['provider']['provider_name']} suitability "
                             f"{p['suitability_score']:.0f}/100" for p in report.providers))
    else:
        trace.skip("score_providers", "No researched providers to score")
        trace.skip("evaluate_suitability", "No researched providers to evaluate")

    analyses = []
    for provider in request.providers:
        rate_adj = report.rate_adjustment if report else 0.0
        advance_adj = report.advance_adjustment if report else 0.0
        analysis_ = analyze_provider(request, provider, research_adjustment=rate_adj,
                                     advance_adjustment=advance_adj)
        analyses.append(analysis_)

    trace.done("check_constraints",
               f"{sum(1 for a in analyses if not a.hard.passed)} providers declined on hard constraints")
    trace.done("price_financing",
               f"Research adjustment {report.rate_adjustment:+.2f} pts" if report else "No research signal applied")
    trace.done("generate_offer",
               f"{sum(1 for a in analyses if a.hard.passed)} offers generated")
    trace.finish()

    return AgentAnalysisResponse(
        offers=[_serialize(a) for a in analyses],
        research=report.to_dict() if report else None,
        trace=trace.to_dict(),
    )


@app.get("/research")
def research_status():
    """Current research telemetry and cache state for the judge."""
    telemetry = _load_telemetry()
    return {
        "telemetry": telemetry,
        "cache": {"directory": _cache_dir_public(), "providers_cached": _cached_provider_count()},
    }


def _cache_dir_public() -> str:
    from .research import _cache_dir
    return _cache_dir()


def _cached_provider_count() -> int:
    from .research import _load_cache
    return len(_load_cache())


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
            "research_adjustment": a.pricing.research_adjustment,
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
