"""Provider intelligence layer: researched profiles -> decision inputs.

Connects Firecrawl research to the Capital Agent's decision:

    researched profile -> provider score -> suitability -> pricing signals

All numbers are deterministic and evidence-backed. Missing evidence is
UNKNOWN and can never inflate a score or a suitability claim.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .research import ProviderResearch, ResearchOutcome
from .scoring import ProviderScore, score_provider


@dataclass
class ProviderIntelligence:
    """Score + suitability + pricing signals for one researched provider."""

    profile: ProviderResearch
    score: ProviderScore
    suitability_score: float          # 0..100
    suitable: bool
    suitability_reasons: list[str] = field(default_factory=list)
    rate_adjustment: float = 0.0      # signed % points applied to agent pricing
    advance_adjustment: float = 0.0   # signed advance-rate delta
    facts: list[dict] = field(default_factory=list)
    inferences: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "provider": self.profile.to_dict(),
            "score": self.score.to_dict(),
            "suitability_score": round(self.suitability_score, 1),
            "suitable": self.suitable,
            "suitability_reasons": self.suitability_reasons,
            "rate_adjustment": round(self.rate_adjustment, 2),
            "advance_adjustment": round(self.advance_adjustment, 3),
            "facts": self.facts,
            "inferences": self.inferences,
        }


def _parse_limit(value: str) -> float | None:
    import re
    if value == "UNKNOWN":
        return None
    cleaned = value.replace(",", "").strip().lower()
    match = re.match(r"([\d.]+)\s*(crore|cr|lakh|l|k)?", cleaned)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or ""
    if unit in ("crore", "cr"):
        number *= 10_000_000
    elif unit in ("lakh", "l"):
        number *= 100_000
    elif unit == "k":
        number *= 1_000
    return number


def _parse_rate(value: str) -> float | None:
    import re
    if value == "UNKNOWN":
        return None
    match = re.search(r"(\d{1,2}(?:\.\d+)?)", value)
    return float(match.group(1)) if match else None


def _split_facts(profile: ProviderResearch) -> tuple[list[dict], list[dict]]:
    facts, inferences = [], []
    for fact in profile.facts:
        entry = fact.to_dict()
        if fact.kind == "AGENT_INFERENCE":
            inferences.append(entry)
        else:
            facts.append(entry)
    return facts, inferences


def evaluate_intelligence(profile: ProviderResearch, invoice, requirements) -> ProviderIntelligence:
    """Score the researched provider and derive deterministic pricing signals."""
    industry = invoice.industry
    score = score_provider(profile, industry)

    facts, inferences = _split_facts(profile)
    reasons: list[str] = []
    suitability = 100.0

    # Published financing limit vs required financing.
    limit = profile.fact("limit")
    limit_value = _parse_limit(limit.value) if limit else None
    if limit and limit.confidence > 0 and limit_value is not None:
        if limit_value < requirements.minimum_amount:
            suitability -= 45
            reasons.append(
                f"Published financing limit ₹{limit_value:,.0f} is below the required "
                f"₹{requirements.minimum_amount:,.0f}."
            )
        elif limit_value < requirements.minimum_amount * 2:
            suitability -= 15
            reasons.append(
                f"Published financing limit ₹{limit_value:,.0f} is tight against the "
                f"required ₹{requirements.minimum_amount:,.0f}."
            )
        else:
            reasons.append(
                f"Published financing limit ₹{limit_value:,.0f} comfortably covers the "
                f"required ₹{requirements.minimum_amount:,.0f}."
            )
    elif limit and limit.value == "UNKNOWN":
        suitability -= 10
        reasons.append("No published financing limit found; capacity is unverified.")

    # SCF capability matters for this product.
    product = profile.fact("product")
    if product and product.confidence > 0:
        reasons.append("Source evidences a supply-chain finance product.")
    else:
        suitability -= 10
        reasons.append("No supply-chain finance product evidence found.")

    # Industry fit.
    sectors = profile.fact("sectors")
    if sectors and sectors.confidence > 0 and industry.lower() in sectors.value.lower():
        reasons.append(f"Source mentions {industry}, matching the invoice industry.")
    elif sectors and sectors.value != "UNKNOWN":
        suitability -= 5
        reasons.append(f"No explicit {industry} mention in the researched source.")

    # Pricing signals: competitive published rates pull the agent's pricing
    # down (capped), absent rates cannot do anything.
    rate_adjustment = 0.0
    rate = profile.fact("rate")
    rate_value = _parse_rate(rate.value) if rate else None
    if rate and rate.confidence > 0 and rate_value is not None:
        # Reference 9% market rate; published 7% -> -0.40pt, 12% -> +0.60pt.
        rate_adjustment = max(-0.75, min(0.75, (rate_value - 9.0) * 0.20))
        reasons.append(
            f"Published rate ~{rate_value}% adjusts the agent's pricing by "
            f"{rate_adjustment:+.2f} points."
        )

    advance_adjustment = 0.0
    advance = profile.fact("advance")
    if advance and advance.confidence > 0:
        import re
        match = re.search(r"(\d{1,3})", advance.value)
        if match:
            published_advance = float(match.group(1)) / 100.0
            advance_adjustment = max(-0.10, min(0.10, published_advance - 0.80))
            reasons.append(
                f"Published advance ~{published_advance:.0%} adjusts the agent's advance "
                f"rate by {advance_adjustment:+.3f}."
            )

    suitability = max(0.0, min(100.0, suitability + score.total * 0.05))
    suitable = suitability >= 50.0
    if not suitable:
        reasons.append("Provider suitability falls below the participation threshold.")

    return ProviderIntelligence(
        profile=profile,
        score=score,
        suitability_score=round(suitability, 1),
        suitable=suitable,
        suitability_reasons=reasons,
        rate_adjustment=round(rate_adjustment, 2),
        advance_adjustment=round(advance_adjustment, 3),
        facts=facts,
        inferences=inferences,
    )


@dataclass
class IntelligenceReport:
    """Full intelligence view returned to the Capital Agents page."""

    research: dict                    # ResearchOutcome serialized
    providers: list[dict]             # ProviderIntelligence serialized per provider
    rate_adjustment: float            # aggregate market pricing signal
    advance_adjustment: float

    def to_dict(self) -> dict:
        return {
            "research": self.research,
            "providers": self.providers,
            "rate_adjustment": round(self.rate_adjustment, 2),
            "advance_adjustment": round(self.advance_adjustment, 3),
        }


def build_intelligence(outcome: ResearchOutcome, invoice, requirements) -> IntelligenceReport:
    """Turn a research outcome into scored intelligence for the agent."""
    intelligences = [
        evaluate_intelligence(profile, invoice, requirements)
        for profile in outcome.providers
    ]
    # Aggregate pricing signal: average of researched providers' adjustments,
    # so a single outlier cannot move the market alone.
    rates = [i.rate_adjustment for i in intelligences]
    advances = [i.advance_adjustment for i in intelligences]
    rate_adjustment = round(sum(rates) / len(rates), 2) if rates else 0.0
    advance_adjustment = round(sum(advances) / len(advances), 3) if advances else 0.0
    return IntelligenceReport(
        research=outcome.to_dict(),
        providers=[i.to_dict() for i in intelligences],
        rate_adjustment=rate_adjustment,
        advance_adjustment=advance_adjustment,
    )
