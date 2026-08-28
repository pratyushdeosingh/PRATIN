"""Capital Agent: the decision-making brain of a capital provider.

The agent evaluates a financing opportunity from the perspective of a
single capital provider. It runs a deterministic pipeline:

    OBSERVE   - read the invoice, verification, risk and provider state
    EVALUATE  - build an explainable opportunity-attractiveness picture
    CONSTRAIN - enforce hard provider gates; fail loudly, never silently
    DECIDE    - participate or decline
    PRICE     - derive rate, advance rate, fees and expected return
    EXPLAIN   - record why every number was chosen
    ACT       - emit a structured Offer

Everything here is deterministic and explainable. The agent is not a loan
calculator: the provider's own state (liquidity, exposure, concentration,
appetite, sector preferences, settlement speed) materially changes the
decision and the terms, and every term carries a plain-language reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256

from contracts.models import (
    MarketRequest,
    Offer,
    Provider,
    VerificationStatus,
)

from .market_data import MarketConditions, load_market


# ---------------------------------------------------------------------------
# Internal analysis record (never serialised into the strict Offer contract)
# ---------------------------------------------------------------------------

@dataclass
class PricingDecomposition:
    """Deterministic breakdown of the final annual financing rate."""

    base_return_rate: float
    risk_premium: float
    tenor_adjustment: float
    industry_adjustment: float
    liquidity_adjustment: float
    portfolio_adjustment: float
    market_adjustment: float
    research_adjustment: float = 0.0
    final_rate: float = 0.0

    def lines(self) -> list[str]:
        """Human-readable decomposition lines, rounded to one basis point."""
        def pct(x: float) -> str:
            return f"{x:+.2f}%"
        return [
            f"Base required return: {self.base_return_rate:.2f}%",
            f"Risk premium: {pct(self.risk_premium)}",
            f"Tenor adjustment: {pct(self.tenor_adjustment)}",
            f"Industry adjustment: {pct(self.industry_adjustment)}",
            f"Liquidity adjustment: {pct(self.liquidity_adjustment)}",
            f"Portfolio adjustment: {pct(self.portfolio_adjustment)}",
            f"Market adjustment: {pct(self.market_adjustment)}",
            f"Research adjustment: {pct(self.research_adjustment)}",
            f"Final annual financing rate: {self.final_rate:.2f}%",
        ]


@dataclass
class AttractivenessFactor:
    """One scored component of the opportunity-attractiveness assessment."""

    label: str
    score: float            # 0..100
    explanation: str


@dataclass
class AttractivenessAssessment:
    """Explainable internal attractiveness score (never a black box)."""

    score: float            # 0..100
    factors: list[AttractivenessFactor] = field(default_factory=list)

    def positive_lines(self) -> list[str]:
        return [f"+ {f.explanation}" for f in self.factors if f.score >= 50]

    def negative_lines(self) -> list[str]:
        return [f"- {f.explanation}" for f in self.factors if f.score < 50]


@dataclass
class HardConstraintResult:
    """Outcome of the hard-constraint gate."""

    passed: bool
    failures: list[str] = field(default_factory=list)


@dataclass
class ProviderAnalysis:
    """Full internal analysis for one provider against one opportunity."""

    provider: Provider
    market: MarketConditions
    hard: HardConstraintResult
    attractiveness: AttractivenessAssessment | None = None
    pricing: PricingDecomposition | None = None
    advance_rate: float | None = None
    financed_amount: float | None = None
    tenor_days: int | None = None
    fees: float | None = None
    total_effective_cost: float | None = None
    expected_return: float | None = None
    settlement_hours: int | None = None
    post_allocation_exposure_ratio: float | None = None
    reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Deterministic helpers
# ---------------------------------------------------------------------------

def _annualized_return(financed: float, fees: float, interest: float, tenor_days: int) -> float:
    """Annualised effective return on the deployed capital.

    Treats fees and interest as upfront yield, annualised over the tenor so
    the number is comparable to ``min_return_rate``. This is a demo metric,
    not a real-world financial forecast.
    """
    if financed <= 0 or tenor_days <= 0:
        return 0.0
    total_yield = fees + interest
    return round(total_yield / financed * (365.0 / tenor_days) * 100.0, 2)


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def observe(request: MarketRequest, provider: Provider, market: MarketConditions) -> dict:
    """OBSERVE: assemble the raw picture the agent will reason about."""
    return {
        "invoice": request.invoice,
        "requirements": request.requirements,
        "verification": request.verification,
        "risk": request.risk,
        "provider": provider,
        "market": market,
    }


def evaluate_attractiveness(ctx: dict) -> AttractivenessAssessment:
    """EVALUATE: internal opportunity-attractiveness assessment.

    Every component carries an explanation. The composite is a weighted
    average with deterministic weights; it informs pricing, not hard gates.
    """
    invoice = ctx["invoice"]
    risk = ctx["risk"]
    provider = ctx["provider"]
    requirements = ctx["requirements"]
    market = ctx["market"]

    factors: list[AttractivenessFactor] = []

    # 1. Invoice risk (inverted: lower risk score is more attractive)
    risk_score = 100.0 - risk.score
    factors.append(AttractivenessFactor(
        label="Invoice risk",
        score=round(max(0.0, min(100.0, risk_score)), 1),
        explanation=f"Risk score {risk.score:.0f} ({risk.band.value}) "
                    f"maps to an attractiveness of {risk_score:.0f}/100.",
    ))

    # 2. Confidence in the risk assessment
    conf = round(risk.confidence * 100.0, 1)
    factors.append(AttractivenessFactor(
        label="Risk confidence",
        score=conf,
        explanation=f"Risk assessment confidence is {conf:.0f}%.",
    ))

    # 3. Buyer quality (credit-worthy buyer)
    buyer_rating = invoice.buyer_rating if invoice.buyer_rating is not None else 0.75
    buyer = round(buyer_rating * 100.0, 1)
    factors.append(AttractivenessFactor(
        label="Buyer quality",
        score=buyer,
        explanation=f"Buyer rating is {buyer_rating:.0%}.",
    ))

    # 4. Payment history
    payment_ratio = invoice.on_time_payment_ratio if invoice.on_time_payment_ratio is not None else 0.86
    pay = round(payment_ratio * 100.0, 1)
    factors.append(AttractivenessFactor(
        label="Payment history",
        score=pay,
        explanation=f"Supplier on-time payment ratio is {payment_ratio:.0%}.",
    ))

    # 5. Prior defaults
    prior_defaults = invoice.prior_defaults if invoice.prior_defaults is not None else 0
    if prior_defaults > 0:
        factors.append(AttractivenessFactor(
            label="Prior defaults",
            score=0.0,
            explanation=f"{prior_defaults} prior default(s) reported.",
        ))
    else:
        factors.append(AttractivenessFactor(
            label="Prior defaults",
            score=100.0,
            explanation="No prior defaults reported.",
        ))

    # 6. Industry fit
    industry = invoice.industry.lower()
    preferred = {x.lower() for x in provider.preferred_industries}
    if industry in preferred:
        factors.append(AttractivenessFactor(
            label="Industry fit",
            score=100.0,
            explanation=f"{invoice.industry} is a preferred industry for {provider.name}.",
        ))
    else:
        factors.append(AttractivenessFactor(
            label="Industry fit",
            score=45.0,
            explanation=f"{invoice.industry} is outside {provider.name}'s preferred industries.",
        ))

    # 7. Tenor fit (shorter is better; do not exceed invoice economic life)
    if invoice.due_date and invoice.issue_date:
        days_to_due = (invoice.due_date - invoice.issue_date).days
    else:
        days_to_due = requirements.desired_tenor_days

    if days_to_due <= 0:
        tenor_score = 0.0
        tenor_note = "Invoice is already past due."
    else:
        tenor_ratio = requirements.desired_tenor_days / days_to_due
        if tenor_ratio <= 1.0:
            tenor_score = 100.0 - max(0.0, min(100.0, (tenor_ratio - 0.5) * 100.0))
            tenor_note = (f"Desired tenor {requirements.desired_tenor_days}d fits the "
                          f"{days_to_due}d invoice life.")
        else:
            tenor_score = 20.0
            tenor_note = (f"Desired tenor {requirements.desired_tenor_days}d exceeds the "
                          f"{days_to_due}d invoice life.")
    factors.append(AttractivenessFactor(
        label="Tenor fit",
        score=round(max(0.0, min(100.0, tenor_score)), 1),
        explanation=tenor_note,
    ))

    # 8. Portfolio state: current exposure ratio
    exposure_ratio = provider.current_exposure / provider.portfolio_capacity
    headroom = provider.max_concentration_ratio - exposure_ratio
    if headroom >= 0.15:
        port = 100.0
        port_note = (f"Exposure is {exposure_ratio:.0%} of capacity, well below the "
                     f"{provider.max_concentration_ratio:.0%} ceiling.")
    elif headroom >= 0.0:
        port = 30.0 + 70.0 * (headroom / 0.15)
        port_note = (f"Exposure is {exposure_ratio:.0%} of capacity, approaching the "
                     f"{provider.max_concentration_ratio:.0%} concentration ceiling.")
    else:
        port = 0.0
        port_note = (f"Exposure {exposure_ratio:.0%} already exceeds the "
                     f"{provider.max_concentration_ratio:.0%} concentration ceiling.")
    factors.append(AttractivenessFactor(
        label="Portfolio headroom",
        score=round(max(0.0, min(100.0, port)), 1),
        explanation=port_note,
    ))

    # 9. Liquidity sufficiency
    requested = requirements.minimum_amount
    if provider.available_liquidity >= requested * 3:
        liq = 100.0
        liq_note = f"Liquidity of ₹{provider.available_liquidity:,.0f} comfortably covers the ₹{requested:,.0f} request."
    elif provider.available_liquidity >= requested:
        liq = 60.0 + 40.0 * (provider.available_liquidity - requested) / max(requested * 2, 1)
        liq_note = f"Liquidity of ₹{provider.available_liquidity:,.0f} covers the ₹{requested:,.0f} request with limited headroom."
    else:
        liq = 0.0
        liq_note = f"Liquidity of ₹{provider.available_liquidity:,.0f} is below the ₹{requested:,.0f} request."
    factors.append(AttractivenessFactor(
        label="Liquidity sufficiency",
        score=round(max(0.0, min(100.0, liq)), 1),
        explanation=liq_note,
    ))

    # 10. Market regime
    market_scores = {
        "FAVORABLE": 85.0,
        "NEUTRAL": 65.0,
        "CAUTIOUS": 40.0,
        "STRESSED": 20.0,
    }
    market_score = market_scores.get(market.regime, 50.0)
    factors.append(AttractivenessFactor(
        label="Market conditions",
        score=market_score,
        explanation=market.description,
    ))

    # Weighted composite (deterministic demo weights).
    weights = {
        "Invoice risk": 0.25,
        "Risk confidence": 0.10,
        "Buyer quality": 0.15,
        "Payment history": 0.10,
        "Prior defaults": 0.10,
        "Industry fit": 0.08,
        "Tenor fit": 0.07,
        "Portfolio headroom": 0.06,
        "Liquidity sufficiency": 0.06,
        "Market conditions": 0.03,
    }
    total = sum(f.score * weights.get(f.label, 0.05) for f in factors)
    score = round(total, 1)
    return AttractivenessAssessment(score=score, factors=factors)


def _liquidity_adjustment(provider: Provider, financed: float) -> tuple[float, str]:
    """Liquidity adjustment: scarcer liquidity demands a higher return."""
    liquidity_after = provider.available_liquidity - financed
    if provider.available_liquidity <= 0:
        return 0.5, "No headroom; liquidity is fully committed."
    ratio = liquidity_after / provider.available_liquidity
    if ratio >= 0.5:
        adj = 0.0
        note = "Liquidity remains comfortable after allocation."
    elif ratio >= 0.2:
        adj = round((0.5 - ratio) * 1.2, 2)
        note = f"Allocation consumes a meaningful share of available liquidity (remaining {ratio:.0%})."
    else:
        adj = 1.2
        note = f"Allocation would nearly exhaust available liquidity (remaining {ratio:.0%})."
    return adj, note


def _portfolio_adjustment(provider: Provider, financed: float) -> tuple[float, str]:
    """Portfolio adjustment: concentration risk raises the demanded return."""
    new_exposure = provider.current_exposure + financed
    new_ratio = new_exposure / provider.portfolio_capacity
    ceiling = provider.max_concentration_ratio
    headroom = ceiling - new_ratio
    if headroom >= 0.15:
        adj = 0.0
        note = "Portfolio concentration stays comfortably inside the ceiling."
    elif headroom >= 0.0:
        adj = round((0.15 - headroom) * 4.0, 2)
        note = (f"Post-allocation exposure {new_ratio:.0%} is close to the "
                f"{ceiling:.0%} concentration ceiling.")
    else:
        adj = 1.5
        note = (f"Post-allocation exposure {new_ratio:.0%} breaches the "
                f"{ceiling:.0%} concentration ceiling.")
    return adj, note


def constrain(ctx: dict) -> HardConstraintResult:
    """CONSTRAIN: enforce the provider's own hard gates.

    A provider declines only when ITS OWN state cannot support the
    opportunity: rejected verification, risk beyond its appetite,
    insufficient liquidity to fund the ticket it can deploy, or a breached
    portfolio concentration ceiling.

    Supplier-side mandates (financing floor, settlement ceiling, total-cost
    ceiling) belong to the marketplace matching layer, which rejects offers
    against them. The agent prices honestly and flags those mismatches on
    the offer instead of turning them into declines here, so the canonical
    "lowest rate loses" story stays intact.
    """
    verification = ctx["verification"]
    risk = ctx["risk"]
    provider = ctx["provider"]
    requirements = ctx["requirements"]

    failures: list[str] = []

    # 1. Verification status
    if verification.status == VerificationStatus.REJECTED:
        failures.append("Invoice verification was rejected.")

    # 2. Risk appetite
    if risk.score > provider.risk_appetite:
        failures.append(
            f"Risk score {risk.score:.0f} exceeds the provider appetite of "
            f"{provider.risk_appetite:.0f}."
        )

    # 3. Available liquidity vs the ticket the provider can deploy
    required_ticket = min(requirements.minimum_amount, provider.max_ticket_size)
    if provider.available_liquidity < required_ticket:
        failures.append(
            f"Available liquidity ₹{provider.available_liquidity:,.0f} cannot fund the "
            f"₹{required_ticket:,.0f} ticket within the provider's ticket size."
        )

    # 4. Portfolio concentration (current and prospective)
    exposure_ratio = provider.current_exposure / provider.portfolio_capacity
    if exposure_ratio >= provider.max_concentration_ratio:
        failures.append(
            f"Current exposure {exposure_ratio:.0%} of capacity has already reached "
            f"the {provider.max_concentration_ratio:.0%} concentration ceiling."
        )
    elif (provider.current_exposure + requirements.minimum_amount) / provider.portfolio_capacity \
            > provider.max_concentration_ratio:
        failures.append(
            f"Allocating ₹{requirements.minimum_amount:,.0f} would push exposure above "
            f"the {provider.max_concentration_ratio:.0%} concentration ceiling."
        )

    return HardConstraintResult(passed=not failures, failures=failures)


def price(ctx: dict, attractiveness: AttractivenessAssessment,
          research_adjustment: float = 0.0, advance_adjustment: float = 0.0) -> tuple[PricingDecomposition, float, float, int, float, float, float]:
    """PRICE: derive the full financing package.

    Returns (decomposition, advance_rate, financed_amount, tenor_days, fees,
    interest, total_effective_cost). Every adjustment is deterministic and
    explainable. ``research_adjustment``/``advance_adjustment`` are optional
    signals from researched provider intelligence; they default to zero so
    the deterministic engine stays fully backward compatible.
    """
    invoice = ctx["invoice"]
    requirements = ctx["requirements"]
    provider = ctx["provider"]
    market = ctx["market"]

    # --- Advance rate -----------------------------------------------------
    industry_fit = invoice.industry.lower() in {x.lower() for x in provider.preferred_industries}
    risk_drag = max(0.0, (risk_score := ctx["risk"].score) - 30.0) / 1000.0
    advance = provider.base_advance_rate
    advance += 0.02 if industry_fit else -0.03
    advance -= risk_drag
    advance += market.advance_rate_adjustment
    advance += advance_adjustment
    advance = round(max(0.50, min(0.95, advance)), 3)

    # --- Financing amount -------------------------------------------------
    financed = round(
        min(invoice.amount * advance, provider.max_ticket_size, provider.available_liquidity),
        2,
    )

    # --- Tenor ------------------------------------------------------------
    tenor = requirements.desired_tenor_days + market.tenor_adjustment_days
    if invoice.due_date and invoice.issue_date:
        days_to_due = (invoice.due_date - invoice.issue_date).days
        tenor = max(1, min(tenor, days_to_due)) if days_to_due > 0 else max(1, tenor)
    else:
        tenor = max(1, tenor)

    # --- Annual financing rate --------------------------------------------
    risk_premium = round(ctx["risk"].score * (0.055 if provider.provider_type == "BANK" else 0.07) / 10.0, 2)
    tenor_adj = round(min(0.8, max(0.0, (tenor - 45) / 200.0)), 2)
    industry_adj = 0.0 if industry_fit else 0.65
    liquidity_adj, _ = _liquidity_adjustment(provider, financed)
    portfolio_adj, _ = _portfolio_adjustment(provider, financed)
    market_adj = round(market.risk_premium_bps / 100.0, 2)
    research_adj = round(research_adjustment, 2)
    base = provider.min_return_rate
    final_rate = round(base + risk_premium + tenor_adj + industry_adj + liquidity_adj + portfolio_adj + market_adj + research_adj, 2)

    decomposition = PricingDecomposition(
        base_return_rate=base,
        risk_premium=risk_premium,
        tenor_adjustment=tenor_adj,
        industry_adjustment=industry_adj,
        liquidity_adjustment=liquidity_adj,
        portfolio_adjustment=portfolio_adj,
        market_adjustment=market_adj,
        research_adjustment=research_adj,
        final_rate=final_rate,
    )

    # --- Fees, interest, total effective cost ------------------------------
    fees = round(financed * provider.fee_rate, 2)
    interest = round(financed * final_rate / 100.0 * tenor / 365.0, 2)
    total_cost = round(interest + fees, 2)

    return decomposition, advance, financed, tenor, fees, interest, total_cost


def _explain_offer(ctx: dict, analysis: ProviderAnalysis) -> None:
    """EXPLAIN: record why this provider participated and on what terms."""
    invoice = ctx["invoice"]
    requirements = ctx["requirements"]
    risk = ctx["risk"]
    provider = analysis.provider
    market = analysis.market
    a = analysis.attractiveness
    p = analysis.pricing

    reasons: list[str] = []

    # Participation
    reasons.append(f"Risk score {risk.score:.0f} is within provider appetite of {provider.risk_appetite:.0f}.")
    industry_fit = invoice.industry.lower() in {x.lower() for x in provider.preferred_industries}
    if industry_fit:
        reasons.append(f"{invoice.industry} is a preferred industry for {provider.name}.")
    else:
        reasons.append(f"{invoice.industry} is not preferred; a sector premium is applied.")
    reasons.append(
        f"Requested financing of ₹{requirements.minimum_amount:,.0f} fits within the "
        f"maximum ticket of ₹{provider.max_ticket_size:,.0f}."
        if requirements.minimum_amount <= provider.max_ticket_size
        else f"Provider maximum ticket of ₹{provider.max_ticket_size:,.0f} is below the "
             f"requested ₹{requirements.minimum_amount:,.0f}; the offer is submitted "
             f"for the marketplace to judge against the financing floor."
    )
    reasons.append(
        f"Current liquidity of ₹{provider.available_liquidity:,.0f} supports the allocation "
        f"of ₹{analysis.financed_amount:,.0f}."
    )

    # Amount
    reasons.append(
        f"Financed amount ₹{analysis.financed_amount:,.0f} = invoice value ₹{invoice.amount:,.0f} "
        f"× advance rate {analysis.advance_rate:.1%}, capped by ticket and liquidity."
    )

    # Advance rate
    reasons.append(
        f"Advance rate {analysis.advance_rate:.1%} starts from base {provider.base_advance_rate:.1%} "
        f"with a {'preferred-sector bonus' if industry_fit else 'non-preferred-sector discount'} "
        f"and a risk adjustment for score {risk.score:.0f}."
    )

    # Rate
    if p is not None:
        reasons.extend(p.lines())

    # Portfolio
    if analysis.post_allocation_exposure_ratio is not None:
        reasons.append(
            f"Post-allocation exposure would be {analysis.post_allocation_exposure_ratio:.0%} "
            f"of capacity against a {provider.max_concentration_ratio:.0%} ceiling."
        )

    # Fees and expected return
    reasons.append(f"Fees of ₹{analysis.fees:,.0f} are charged at the provider fee rate of {provider.fee_rate:.2%}.")
    reasons.append(
        f"Expected annualised return is {analysis.expected_return:.2f}% on the financed "
        f"amount over {analysis.tenor_days} days (demo metric, not a forecast)."
    )

    # Market
    reasons.append(f"Market regime is {market.regime} ({market.source}). {market.description}")

    # Attractiveness summary
    if a is not None:
        reasons.append(f"Opportunity attractiveness: {a.score:.0f}/100.")
        reasons.extend(a.positive_lines())
        reasons.extend(a.negative_lines())

    analysis.reasons = reasons


def act(request: MarketRequest, analysis: ProviderAnalysis) -> Offer:
    """ACT: emit the structured Offer for this provider."""
    offer_id = "OFF-" + sha256(f"{request.opportunity_id}|{analysis.provider.id}".encode()).hexdigest()[:10].upper()
    if not analysis.hard.passed:
        return Offer(
            id=offer_id,
            opportunity_id=request.opportunity_id,
            provider_id=analysis.provider.id,
            provider_name=analysis.provider.name,
            provider_type=analysis.provider.provider_type,
            status="DECLINE",
            reasons=analysis.hard.failures or ["Provider declined."],
        )
    return Offer(
        id=offer_id,
        opportunity_id=request.opportunity_id,
        provider_id=analysis.provider.id,
        provider_name=analysis.provider.name,
        provider_type=analysis.provider.provider_type,
        status="OFFER",
        annual_rate=analysis.pricing.final_rate,
        advance_rate=analysis.advance_rate,
        financed_amount=analysis.financed_amount,
        fees=analysis.fees,
        tenor_days=analysis.tenor_days,
        settlement_hours=analysis.settlement_hours,
        total_effective_cost=analysis.total_effective_cost,
        expected_return=analysis.expected_return,
        reasons=analysis.reasons,
    )


def analyze_provider(
    request: MarketRequest,
    provider: Provider,
    market: MarketConditions | None = None,
    research_adjustment: float = 0.0,
    advance_adjustment: float = 0.0,
) -> ProviderAnalysis:
    """Run the full agent pipeline for one provider against one opportunity.

    Optional researched-intelligence signals adjust pricing; they default to
    zero so the deterministic engine remains fully backward compatible.
    """
    market = market or load_market()
    ctx = observe(request, provider, market)
    hard = constrain(ctx)
    if not hard.passed:
        return ProviderAnalysis(provider=provider, market=market, hard=hard)

    attractiveness = evaluate_attractiveness(ctx)
    (decomposition, advance, financed, tenor, fees, interest, total_cost) = price(
        ctx, attractiveness, research_adjustment, advance_adjustment)

    analysis = ProviderAnalysis(
        provider=provider,
        market=market,
        hard=hard,
        attractiveness=attractiveness,
        pricing=decomposition,
        advance_rate=advance,
        financed_amount=financed,
        tenor_days=tenor,
        fees=fees,
        total_effective_cost=total_cost,
        expected_return=_annualized_return(financed, fees, interest, tenor),
        settlement_hours=provider.settlement_hours,
        post_allocation_exposure_ratio=round((provider.current_exposure + financed) / provider.portfolio_capacity, 4),
    )
    _explain_offer(ctx, analysis)
    return analysis


def generate_market(
    request: MarketRequest,
    market: MarketConditions | None = None,
) -> list[ProviderAnalysis]:
    """Run the Capital Agent over every provider in the request.

    Returns the full internal analyses (used by the engine to build the
    MarketResponse and by tests to inspect agent reasoning).
    """
    market = market or load_market()
    return [analyze_provider(request, provider, market) for provider in request.providers]
